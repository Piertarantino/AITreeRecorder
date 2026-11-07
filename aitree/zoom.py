"""Import delle tracce per persona dalla registrazione locale di Zoom.

In Zoom: Impostazioni > Registrazione > "Registra un file audio separato per ogni
partecipante". A fine riunione Zoom crea, di solito in Documenti\\Zoom\\<data titolo>,
una cartella "Audio Record" con un file per persona, es. audioMarioRossi21234567890.m4a.
Tutti i file partono dall'inizio della riunione, quindi sono già allineati.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import soundfile as sf

AUDIO_EXT = {".m4a", ".mp3", ".wav", ".aac"}


def speaker_name(file: Path) -> str:
    m = re.match(r"^audio(.*?)\d*$", file.stem)
    raw = (m.group(1) if m else file.stem) or file.stem
    # "MarioRossi" -> "Mario Rossi"
    return re.sub(r"(?<=[a-zàèéìòù])(?=[A-Z])", " ", raw).strip(" _-") or file.stem


def find_tracks(folder: Path) -> list[Path]:
    candidates = [folder / "Audio Record", folder]
    for c in candidates:
        if c.is_dir():
            files = sorted(f for f in c.iterdir() if f.suffix.lower() in AUDIO_EXT and f.stem.lower().startswith("audio"))
            if files:
                return files
    return []


def latest_zoom_folder(since_epoch: float) -> Path | None:
    root = Path.home() / "Documents" / "Zoom"
    if not root.is_dir():
        return None
    recent = [d for d in root.iterdir() if d.is_dir() and d.stat().st_mtime >= since_epoch and find_tracks(d)]
    return max(recent, key=lambda d: d.stat().st_mtime) if recent else None


ENV_RATE = 100   # inviluppo a 100 punti al secondo (10 ms)


def _envelope(wav: Path) -> np.ndarray:
    data, sr = sf.read(wav, dtype="float32", always_2d=True)
    x = np.abs(data.mean(axis=1))
    hop = sr // ENV_RATE
    n = len(x) // hop
    return x[: n * hop].reshape(n, hop).mean(axis=1)


def find_offset(zoom_wavs: list[Path], ref_wavs: list[Path], max_lag_s: float = 900) -> float:
    """Secondi da aggiungere alle tracce Zoom per allinearle alla nostra registrazione.

    Confronta il "profilo del volume" della somma delle tracce Zoom con quello
    della nostra registrazione (correlazione incrociata): niente IA, pochi ms.
    """
    def total(paths):
        envs = [_envelope(p) for p in paths if p.exists()]
        n = max(len(e) for e in envs)
        out = np.zeros(n, dtype=np.float32)
        for e in envs:
            out[: len(e)] += e
        return out

    z, r = total(zoom_wavs), total(ref_wavs)
    z = (z - z.mean()) / (z.std() + 1e-9)
    r = (r - r.mean()) / (r.std() + 1e-9)
    n = 1 << int(np.ceil(np.log2(len(z) + len(r))))
    corr = np.fft.irfft(np.fft.rfft(r, n) * np.conj(np.fft.rfft(z, n)), n)
    lags = np.concatenate([np.arange(0, n // 2), np.arange(-n // 2, 0)])
    keep = np.abs(lags) <= max_lag_s * ENV_RATE
    best = lags[keep][np.argmax(corr[keep])]
    return float(best) / ENV_RATE


def _shift(src: Path, dst: Path, offset: float, length: int) -> None:
    data, sr = sf.read(src, dtype="int16")
    shift = int(round(offset * sr))
    out = np.zeros(length, dtype=np.int16)
    if shift >= 0:
        chunk = data[: max(0, length - shift)]
        out[shift: shift + len(chunk)] = chunk
    else:
        chunk = data[-shift: -shift + length]
        out[: len(chunk)] = chunk
    sf.write(dst, out, sr, subtype="PCM_16")


def prepare_tracks(zoom_folder: Path, folder: Path, ref_wavs: list[Path], limit: int = 16) -> tuple[list[tuple[str, Path]], float]:
    """Decodifica le tracce Zoom, le allinea alla call e ritorna [(nome, wav)]."""
    from .ffmpeg import decode_mono

    files = find_tracks(zoom_folder)[:limit]
    tmp = folder / "persone"
    tmp.mkdir(exist_ok=True)
    raw = []
    for i, f in enumerate(files):
        dst = tmp / f"zoom-{i:02}.wav"
        decode_mono(f, dst)
        raw.append((speaker_name(f), dst))
    offset = find_offset([p for _, p in raw], ref_wavs)
    length = int(sf.info(ref_wavs[0]).duration * 16000)
    people = []
    for i, (name, p) in enumerate(raw):
        dst = tmp / f"{i:02}-{re.sub(r'[^A-Za-z0-9]+', '_', name)[:40]}.wav"
        _shift(p, dst, offset, length)
        p.unlink()
        people.append((name, dst))
    return people, offset
