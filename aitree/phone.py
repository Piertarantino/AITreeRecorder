"""Registrazioni fatte col telefono (app Android) e arrivate sul PC via Google Drive.

L'app salva file come `2026-11-07_10-33_Telefono_Riunione-cliente.ogg` (Opus, mono)
in una cartella di Drive. Qui ognuno diventa una cartella di call come quelle del
PC: audio.ogg, trascrizione, report e pacchetto per IA.

    python -m aitree telefono "G:\\Il mio Drive\\AI-TREE Telefono" [--resta]

Il telefono ha un solo microfono: le voci non sono separate, tutto il parlato
finisce sotto un unico nome ("Voce").
"""
from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from . import ffmpeg
from .config import Config

AUDIO_EXT = {".ogg", ".opus", ".m4a", ".mp3", ".wav", ".aac", ".3gp"}
SPEAKER = "Voce"
NAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})")


def _started_at(src: Path) -> float:
    m = NAME_RE.match(src.stem)
    if m:
        try:
            return datetime(*map(int, m.groups())).timestamp()
        except ValueError:
            pass
    return src.stat().st_mtime


def _title(src: Path, started: float) -> str:
    rest = src.stem.split("_Telefono_", 1)
    label = rest[1].replace("-", " ") if len(rest) == 2 else "Telefono"
    return f"{label} {datetime.fromtimestamp(started):%d/%m/%Y %H:%M}"


def _duration(path: Path) -> float:
    try:
        out = ffmpeg._run([ffmpeg.find_ffmpeg("ffprobe"), "-v", "error", "-show_entries",
                           "format=duration", "-of", "json", str(path)]).stdout
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 0.0


def target_folder(cfg: Config, src: Path) -> Path:
    started = datetime.fromtimestamp(_started_at(src))
    return Path(cfg.output_dir) / started.strftime("%Y-%m") / src.stem


def pending(cfg: Config, inbox: Path) -> list[Path]:
    """File audio nuovi e già sincronizzati del tutto (fermi da almeno 30 s)."""
    out = []
    for f in sorted(inbox.iterdir()):
        if f.suffix.lower() not in AUDIO_EXT or not f.is_file():
            continue
        if time.time() - f.stat().st_mtime < 30:
            continue  # Drive lo sta ancora scaricando
        meta = target_folder(cfg, f) / "meta.json"
        if meta.exists() and json.loads(meta.read_text(encoding="utf-8")).get("finalized"):
            continue
        out.append(f)
    return out


def process(src: Path, cfg: Config) -> Path:
    from .llm import build_pack, open_chat, send
    from .merge import to_json, to_markdown, to_srt
    from .report import build_report
    from .session import transcript_lines
    from .transcribe import load_model, transcribe_track

    folder = target_folder(cfg, src)
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / ("audio" + src.suffix.lower())
    shutil.copy2(src, audio)

    started = _started_at(src)
    meta = {
        "title": _title(src, started),
        "app": "Telefono (un solo microfono, voci non separate)",
        "source": "android",
        "source_file": str(src),
        "started_at": started,
        "duration_s": round(_duration(audio), 1),
        "quality": "audio",
        "language": cfg.language,
        "audio_tracks": [SPEAKER],
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    wav = folder / "voce.wav"
    ffmpeg.decode_mono(audio, wav)
    lang = None if cfg.language == "auto" else cfg.language
    model, desc = load_model()
    print(f"  {src.name}: trascrivo con {desc}...")
    t = time.time()
    segs = transcribe_track(model, wav, SPEAKER, lang)
    print(f"  {len(segs)} frasi in {time.time() - t:.0f} s")
    if not meta["duration_s"] and segs:
        meta["duration_s"] = round(segs[-1].end, 1)

    title = meta["title"]
    (folder / "trascrizione.md").write_text(to_markdown(segs, title), encoding="utf-8")
    (folder / "trascrizione.srt").write_text(to_srt(segs), encoding="utf-8")
    (folder / "trascrizione.json").write_text(to_json(segs), encoding="utf-8")
    report = build_report(meta, segs)
    (folder / "report.md").write_text(report, encoding="utf-8")
    me = cfg.my_name or "Io"
    pack_text = build_pack(meta, report, transcript_lines(segs), cfg.llm.prompt, me)
    pack = folder / "pacchetto-llm.md"
    pack.write_text(pack_text, encoding="utf-8")

    if cfg.llm.auto_send and cfg.llm.provider:
        try:
            answer = send(cfg.llm.provider, pack_text, cfg.llm.api_key, cfg.llm.model)
            (folder / "riassunto-ia.md").write_text(answer, encoding="utf-8")
        except Exception as exc:
            print(f"  Invio all'IA non riuscito: {exc}")
    if cfg.llm.open_chat:
        print("  " + open_chat(cfg.llm.open_chat, pack))

    if not cfg.keep_wav:
        wav.unlink(missing_ok=True)
    meta["finalized"] = True
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"■ Pronto: {folder}")
    return folder


def run(inbox: Path, cfg: Config, keep_watching: bool = False, every_s: int = 60) -> None:
    if not inbox.is_dir():
        raise SystemExit(f"Cartella non trovata: {inbox}")
    while True:
        for f in pending(cfg, inbox):
            try:
                process(f, cfg)
            except Exception as exc:
                print(f"  {f.name}: non elaborato ({exc})")
        if not keep_watching:
            return
        time.sleep(every_s)
