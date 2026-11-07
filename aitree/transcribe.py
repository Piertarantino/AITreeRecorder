"""Trascrizione locale con faster-whisper, con scelta automatica GPU NVIDIA / CPU."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Modello per hardware: grande e preciso su NVIDIA, piccolo e veloce su CPU.
GPU_MODEL = "large-v3-turbo"
CPU_MODEL = "small"


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str


def pick_device(mode: str | None = None) -> tuple[str, str, str]:
    """Ritorna (device, compute_type, modello). mode: auto | nvidia | cpu (da config "gpu")."""
    from . import gpu
    from .config import load

    mode = mode or load().gpu
    if mode == "cpu":
        return "cpu", "int8", CPU_MODEL
    if gpu.has_nvidia():
        if gpu.libs_ready():
            gpu.enable()
            return "cuda", "float16", GPU_MODEL
        print(f"Scheda {gpu.gpu_name()} trovata, ma manca il supporto GPU: scaricalo dalle "
              "impostazioni (GPU → NVIDIA) per trascrivere 5-10 volte più veloce. Per ora uso la CPU.")
    return "cpu", "int8", CPU_MODEL


def load_model(model: str | None = None, mode: str | None = None):
    from faster_whisper import WhisperModel

    device, compute, default_model = pick_device(mode)
    name = model or default_model
    if device == "cuda":
        try:
            m = WhisperModel(name, device="cuda", compute_type=compute)
            # Prova vera: senza le librerie CUDA l'errore arriva solo alla prima trascrizione.
            import numpy as np
            list(m.transcribe(np.zeros(16000, dtype=np.float32), language="it")[0])
            return m, f"{name} su GPU NVIDIA"
        except Exception as exc:  # driver o librerie non adatti: si ripiega sulla CPU
            print(f"GPU non utilizzabile ({exc}), passo alla CPU.")
            name = model or CPU_MODEL
    return WhisperModel(name, device="cpu", compute_type="int8"), f"{name} su CPU"


def transcribe_track(model, wav: Path, speaker: str, language: str | None) -> list[Segment]:
    if not wav.exists() or wav.stat().st_size < 1000:
        return []
    segments, _info = model.transcribe(
        str(wav),
        language=language,               # None = rilevamento automatico
        vad_filter=True,                 # salta i silenzi (VAD Silero, leggerissimo)
        vad_parameters={"min_silence_duration_ms": 500},
        beam_size=5,
        condition_on_previous_text=False,  # evita ripetizioni a catena
    )
    return [Segment(s.start, s.end, s.text.strip(), speaker) for s in segments if s.text.strip()]
