"""Cattura audio su due tracce separate: microfono (tu) e audio di sistema (gli altri).

Su Windows usa WASAPI tramite la libreria `soundcard`. Il loopback WASAPI non
manda dati quando il PC è in silenzio: per non perdere la sincronia ogni traccia
viene riempita di silenzio quando resta indietro rispetto all'orologio comune.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 48000
BLOCK = 4800            # 100 ms
MAX_LAG_S = 0.25        # oltre questo ritardo inseriamo silenzio
IS_MAC = sys.platform == "darwin"


class TrackRecorder(threading.Thread):
    """Registra una sorgente in un WAV mono, allineato all'orologio comune t0."""

    def __init__(self, name: str, device, path: Path, t0: float, stop: threading.Event):
        super().__init__(name=name, daemon=True)
        self.device, self.path, self.t0, self.stop = device, path, t0, stop
        self.frames = 0
        self.peak = 0.0
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            with sf.SoundFile(self.path, "w", SAMPLE_RATE, 1, "PCM_16") as out, \
                    warnings.catch_warnings():
                # soundcard avvisa a ogni blocco di silenzio del loopback: non serve.
                warnings.simplefilter("ignore")
                with open_recorder(self.device) as rec:
                    while not self.stop.is_set():
                        data = rec.record(numframes=BLOCK)
                        mono = data.mean(axis=1) if data.ndim == 2 else data
                        self._pad_to_clock(out, len(mono))
                        out.write(mono.astype(np.float32))
                        self.frames += len(mono)
                        if len(mono):
                            self.peak = max(self.peak * 0.9, float(np.abs(mono).max()))
        except Exception as exc:  # riportato dal chiamante
            self.error = exc

    def _pad_to_clock(self, out: sf.SoundFile, incoming: int) -> None:
        expected = int((time.perf_counter() - self.t0) * SAMPLE_RATE) - incoming
        lag = expected - self.frames
        if lag > MAX_LAG_S * SAMPLE_RATE:
            out.write(np.zeros(lag, dtype=np.float32))
            self.frames += lag


def open_recorder(device):
    """Apre la sorgente a 48 kHz mono.

    Su Mac (CoreAudio) il blocco interno deve stare tra ~15 e 512 campioni e dipende
    dal dispositivo: lo lasciamo scegliere a CoreAudio. Leggiamo comunque 100 ms alla
    volta con record(numframes=BLOCK), che accumula i blocchi piccoli.
    """
    if IS_MAC:
        return device.recorder(samplerate=SAMPLE_RATE, channels=1)
    try:
        return device.recorder(samplerate=SAMPLE_RATE, channels=1, blocksize=BLOCK)
    except TypeError as exc:
        if "blocksize" not in str(exc):
            raise
        return device.recorder(samplerate=SAMPLE_RATE, channels=1)


def test_microphone(seconds: float = 0.3) -> str:
    """Apre davvero il microfono predefinito e legge un po' di audio (per il selftest)."""
    import soundcard as sc
    mic = sc.default_microphone()
    if mic is None:
        return "nessun microfono (saltato)"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with open_recorder(mic) as rec:
            n = 0
            while n < int(seconds * SAMPLE_RATE):
                n += len(rec.record(numframes=BLOCK))
    return f"{mic.name}: {n} campioni letti"


def default_devices():
    """(microfono, sorgente "Loro", nome uscita). Su Mac "Loro" arriva dall'helper."""
    import soundcard as sc

    mic = sc.default_microphone()
    if IS_MAC:
        return mic, None, "Audio del Mac (ScreenCaptureKit)"
    speaker = sc.default_speaker()
    loopback = sc.get_microphone(id=str(speaker.name), include_loopback=True)
    return mic, loopback, speaker.name


class MacSystemAudio:
    """Audio del Mac tramite aitree-helper (ScreenCaptureKit), allineato a t0 a fine registrazione."""

    def __init__(self, path: Path):
        self.path = path
        self.raw = path.with_name("system_raw.wav")
        self.proc: subprocess.Popen | None = None
        self.epoch = 0.0
        self.error: Exception | None = None
        self.name = "system"

    def start(self) -> None:
        helper = helper_path()
        self.proc = subprocess.Popen([helper, "sysaudio", str(self.raw)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline().strip()  # "READY <epoch>"
        if not line.startswith("READY"):
            err = self.proc.stderr.read() if self.proc.poll() is not None else line
            raise RuntimeError(f"Audio del Mac non disponibile: {err.strip() or 'helper non avviato'}")
        self.epoch = float(line.split()[1])

    @property
    def peak(self) -> float:
        try:  # legge gli ultimi 100 ms scritti (PCM 16 bit)
            with open(self.raw, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                if size < 50_000:
                    return 0.0
                f.seek(size - 9600)
                data = np.frombuffer(f.read(9600), dtype=np.int16)
            return float(np.abs(data).max()) / 32768
        except OSError:
            return 0.0

    def stop(self, t0_epoch: float, duration: float) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write("q\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
        length = int(duration * SAMPLE_RATE)
        out = np.zeros(length, dtype=np.float32)
        if self.raw.exists():
            data, sr = sf.read(self.raw, dtype="float32")
            if data.ndim == 2:
                data = data.mean(axis=1)
            shift = int(round((self.epoch - t0_epoch) * SAMPLE_RATE))
            if shift >= 0:
                chunk = data[: max(0, length - shift)]
                out[shift: shift + len(chunk)] = chunk
            else:
                chunk = data[-shift: -shift + length]
                out[: len(chunk)] = chunk
            self.raw.unlink(missing_ok=True)
        sf.write(self.path, out, SAMPLE_RATE, subtype="PCM_16")


def helper_path() -> str:
    here = Path(__file__).resolve().parent.parent
    bundle = Path(getattr(sys, "_MEIPASS", here))  # app impacchettata
    for cand in (bundle / "bin" / "aitree-helper", here / "bin" / "aitree-helper", here / "mac" / "build" / "aitree-helper"):
        if cand.exists():
            return str(cand)
    raise FileNotFoundError("aitree-helper non trovato: lancia prima mac/build-mac.sh")


def record(folder: Path, should_stop=None, on_tick=None) -> dict:
    """Registra finché should_stop() diventa vero (o Ctrl+C). Ritorna i metadati."""
    folder.mkdir(parents=True, exist_ok=True)
    mic, loopback, speaker_name = default_devices()
    stop = threading.Event()
    mac_sys = MacSystemAudio(folder / "system.wav") if IS_MAC else None
    if mac_sys:
        mac_sys.start()
    t0 = time.perf_counter()
    started = time.time()
    tracks = [TrackRecorder("mic", mic, folder / "mic.wav", t0, stop)]
    if not mac_sys:
        tracks.append(TrackRecorder("system", loopback, folder / "system.wav", t0, stop))
    for t in tracks:
        t.start()
    sys_src = mac_sys or tracks[1]
    try:
        while not stop.is_set():
            time.sleep(0.5)
            for t in tracks:
                if t.error:
                    raise RuntimeError(f"Errore sulla traccia {t.name}: {t.error}")
            if mac_sys and mac_sys.proc.poll() is not None:
                raise RuntimeError("La cattura dell'audio del Mac si è interrotta: " + mac_sys.proc.stderr.read())
            if on_tick:
                on_tick(time.perf_counter() - t0, tracks[0].peak, sys_src.peak)
            if should_stop and should_stop():
                break
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for t in tracks:
            t.join(timeout=3)
        duration = time.perf_counter() - t0
        if mac_sys:
            mac_sys.stop(started, duration)
    return {
        "started_at": started,
        "duration_s": round(duration, 2),
        "microphone": str(mic.name),
        "speaker": str(speaker_name),
        "sample_rate": SAMPLE_RATE,
    }
