"""Impostazioni e preset di "peso" della registrazione.

Le impostazioni stanno in %APPDATA%\\AI-TREE\\config.json e si possono
sovrascrivere da riga di comando.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Preset:
    label: str
    video: bool
    max_width: int      # 0 = risoluzione nativa
    fps: int
    quality: int        # qualità costante: più alto = file più leggero (scala CRF/CQ di H.264)
    max_kbps: int       # tetto del bitrate variabile
    opus_kbps: int      # per traccia audio, mono


# Video a bitrate variabile: quasi niente quando lo schermo è fermo, sale solo
# quando qualcosa si muove (condivisione schermo, video), fino al tetto.
PRESETS: dict[str, Preset] = {
    "audio":   Preset("Solo audio",                     False,    0,  0,  0,    0, 24),
    "leggera": Preset("Leggera (default) ~60-150 MB/h",  True,  1280,  5, 34,  600, 24),
    "media":   Preset("Media ~150-400 MB/h",            True,  1920, 10, 29, 1500, 32),
    "alta":    Preset("Alta ~0,5-1,2 GB/h",             True,     0, 30, 24, 4000, 64),
}
DEFAULT_PRESET = "leggera"

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "AI-TREE"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class EmailSettings:
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    username: str = ""
    password: str = ""          # meglio una "password per le app", non quella dell'account
    sender: str = ""
    to: list[str] = field(default_factory=list)
    attach_transcript: bool = True


@dataclass
class LLMSettings:
    # Pacchetto: sempre creato (pacchetto-llm.md), va bene per qualsiasi IA.
    provider: str = ""          # "" = nessun invio | claude | openai | gemini
    api_key: str = ""           # oppure variabili ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
    model: str = ""             # vuoto = default del provider (Claude: claude-opus-5-5)
    auto_send: bool = False     # invia da solo a fine call e salva riassunto-ia.md
    open_chat: str = ""         # "" | claude | chatgpt | gemini: apre la chat e copia il pacchetto
    prompt: str = ""            # istruzioni personalizzate (vuoto = quelle di default)


@dataclass
class Config:
    quality: str = DEFAULT_PRESET           # audio | leggera | media | alta
    capture: str = "schermo"                # schermo | finestra
    language: str = "it"                    # it, en, ... oppure auto
    gpu: str = "auto"                       # auto (usa NVIDIA se pronta) | nvidia | cpu
    output_dir: str = str(Path.home() / ("Movies" if sys.platform == "darwin" else "Videos") / "AI-TREE Call")
    keep_wav: bool = False                  # tieni anche i WAV originali (pesanti)
    min_free_gb: float = 2.0
    call_apps: list[str] = field(default_factory=lambda: [
        "zoom", "teams", "ms-teams", "msteams", "webex", "slack", "skype",
        "chrome", "msedge", "edgemac", "safari", "firefox", "brave", "opera", "whatsapp", "discord",
        "facetime",
    ])
    phone_inbox: str = ""                   # cartella (es. Google Drive) dove l'app Android salva le registrazioni
    my_name: str = ""                       # se impostato, sostituisce "Io" nelle trascrizioni
    email: EmailSettings = field(default_factory=EmailSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)

    @property
    def preset(self) -> Preset:
        return PRESETS.get(self.quality, PRESETS[DEFAULT_PRESET])


def load() -> Config:
    cfg = Config()
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    for k, v in raw.items():
        if k == "email" and isinstance(v, dict):
            cfg.email = EmailSettings(**{kk: vv for kk, vv in v.items() if kk in EmailSettings.__dataclass_fields__})
        elif k == "llm" and isinstance(v, dict):
            cfg.llm = LLMSettings(**{kk: vv for kk, vv in v.items() if kk in LLMSettings.__dataclass_fields__})
        elif k in Config.__dataclass_fields__:
            setattr(cfg, k, v)
    return cfg


def save(cfg: Config) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    return CONFIG_FILE
