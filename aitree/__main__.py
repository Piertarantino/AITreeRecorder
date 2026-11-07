"""AI Tree Recorder.

  pythonw -m aitree ui                    interfaccia con icona vicino all'orologio
  python -m aitree auto                   resta in attesa: registra da solo ogni call
  python -m aitree record                 registra subito; Ctrl+C per fermare
  python -m aitree finalize CARTELLA      rifà unione/trascrizione/report di una call
  python -m aitree zoom CARTELLA_CALL     ritrascrive usando le tracce per persona di Zoom
  python -m aitree llm CARTELLA [--invia claude|openai|gemini] [--apri claude|chatgpt|gemini]
  python -m aitree telefono [CARTELLA] [--resta]   trascrive le registrazioni dell'app Android
  python -m aitree config                 crea/mostra il file di impostazioni
  python -m aitree devices                microfono e uscita audio in uso

Opzioni comuni: --qualita audio|leggera|media|alta  --cattura schermo|finestra
                --lingua it|en|auto
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from . import config as config_mod
from .config import PRESETS


def _tick(elapsed, mic_peak, sys_peak):
    bar = lambda p: "#" * min(16, int(p * 32))
    sys.stdout.write(f"\r  ● REC {int(elapsed)//3600}:{int(elapsed)%3600//60:02}:{int(elapsed)%60:02}"
                     f"  Io [{bar(mic_peak):<16}]  Loro [{bar(sys_peak):<16}]")
    sys.stdout.flush()


def _apply_overrides(cfg, args):
    if getattr(args, "qualita", None):
        cfg.quality = args.qualita
    if getattr(args, "cattura", None):
        cfg.capture = args.cattura
    if getattr(args, "lingua", None):
        cfg.language = args.lingua
    return cfg


def cmd_record(cfg, args) -> None:
    from .detect import active_call_app, main_window_of
    from .session import DISCLAIMER, finalize, record_call

    print(DISCLAIMER)
    app = active_call_app(cfg.call_apps)
    window = main_window_of(app) if (app and cfg.capture == "finestra") else None
    print(f"  Qualità: {cfg.preset.label}. Premi Ctrl+C per fermare.\n")
    folder = record_call(cfg, app=app, window_title=window, on_tick=_tick)
    print("\n■ Registrazione fermata.")
    if not args.solo_registra:
        finalize(folder, cfg)


def cmd_auto(cfg, args) -> None:
    """Attende che un'app di call prenda il microfono, registra, e ricomincia."""
    from .controller import Controller
    from .session import DISCLAIMER

    print(DISCLAIMER)
    print(f"  Modalità automatica · qualità {cfg.preset.label} · cattura {cfg.capture}")
    print("  In attesa di una call (Zoom, Teams, Meet, ...). Ctrl+C per uscire.\n")
    ctl = Controller(cfg)
    ctl.auto = True
    ctl.start()
    try:
        while True:
            time.sleep(0.5)
            if ctl.state == "registrazione":
                _tick(ctl.elapsed, *ctl.levels)
    except KeyboardInterrupt:
        print("\nUscita.")
        ctl.quit()


def cmd_phone(cfg, args) -> None:
    from .phone import run
    folder = args.cartella or cfg.phone_inbox
    if not folder:
        sys.exit("Indica la cartella delle registrazioni del telefono (o phone_inbox in config.json).")
    run(Path(folder), cfg, args.resta)


def cmd_ui(cfg, args) -> None:
    from .ui import main as ui_main
    ui_main()


def cmd_finalize(cfg, args) -> None:
    from .session import finalize
    finalize(Path(args.cartella), cfg)


def cmd_zoom(cfg, args) -> None:
    from .session import finalize
    from .zoom import find_tracks

    zdir = Path(args.zoom) if args.zoom else None
    if zdir is None:
        from .zoom import latest_zoom_folder
        meta = json.loads((Path(args.cartella) / "meta.json").read_text(encoding="utf-8"))
        zdir = latest_zoom_folder(meta["started_at"] - 60)
    if not zdir or not find_tracks(zdir):
        sys.exit("Nessuna traccia per persona di Zoom trovata. Indica la cartella con --zoom.")
    finalize(Path(args.cartella), cfg, zoom_folder=zdir)


def cmd_llm(cfg, args) -> None:
    from .llm import open_chat, send

    folder = Path(args.cartella)
    pack = folder / "pacchetto-llm.md"
    if not pack.exists():
        sys.exit("pacchetto-llm.md non trovato: esegui prima finalize.")
    if args.invia:
        out = send(args.invia, pack.read_text(encoding="utf-8"),
                   cfg.llm.api_key if cfg.llm.provider == args.invia else "",
                   args.modello or (cfg.llm.model if cfg.llm.provider == args.invia else ""))
        (folder / "riassunto-ia.md").write_text(out, encoding="utf-8")
        print(f"Salvato: {folder / 'riassunto-ia.md'}")
    if args.apri:
        print(open_chat(args.apri, pack))
    if not (args.invia or args.apri):
        print(pack)


def cmd_config(cfg, args) -> None:
    if not config_mod.CONFIG_FILE.exists():
        config_mod.save(cfg)
        print("Creato il file di impostazioni.")
    print(config_mod.CONFIG_FILE)
    print(json.dumps({k: v for k, v in asdict(cfg).items() if k != "email"}, ensure_ascii=False, indent=2))
    print("\nQualità disponibili:")
    for k, p in PRESETS.items():
        print(f"  {k:<8} {p.label}")


def cmd_devices(cfg, args) -> None:
    from .capture import default_devices
    from .detect import apps_using_mic
    from .ffmpeg import pick_encoder

    mic, _loop, speaker = default_devices()
    print(f"Microfono (Io):        {mic.name}")
    print(f"Uscita audio (Loro):   {speaker}")
    print(f"Encoder video:         {pick_encoder()}")
    print(f"App che usano il mic:  {', '.join(apps_using_mic()) or 'nessuna'}")
    if sys.platform == "darwin":
        from .capture import helper_path
        r = subprocess.run([helper_path(), "check"], capture_output=True, text=True)
        print(f"Permesso schermo/audio: {(r.stdout or r.stderr).strip()}")


def cmd_selftest(cfg, args) -> None:
    """Controllo dell'app impacchettata: librerie, ffmpeg, encoder, helper. Usato dalla build."""
    import importlib
    import platform
    lines, ok = [f"AI Tree Recorder selftest · {platform.platform()}"], True

    def check(label, fn):
        nonlocal ok
        try:
            lines.append(f"OK   {label}: {fn()}")
        except Exception as exc:
            ok = False
            lines.append(f"FAIL {label}: {exc!r}")

    for mod in ("numpy", "soundfile", "soundcard", "psutil", "PIL", "tkinter", "faster_whisper",
                "ctranslate2", "onnxruntime", "av"):
        check(f"import {mod}", lambda m=mod: getattr(importlib.import_module(m), "__version__", "ok"))
    from . import ffmpeg as ff
    check("ffmpeg", ff.find_ffmpeg)
    check("ffprobe", lambda: ff.find_ffmpeg("ffprobe"))
    check("opus", lambda: " ".join(ff.opus_args(24)[:2]))
    check("encoder video", ff.pick_encoder)
    check("VAD silero", lambda: __import__("faster_whisper.vad", fromlist=["x"]).get_vad_model() and "ok")
    if sys.platform == "darwin" and int(platform.mac_ver()[0].split(".")[0]) >= 14:
        from .capture import helper_path
        check("helper", lambda: subprocess.run([helper_path(), "mic-users"], capture_output=True,
                                               timeout=10).returncode == 0 or (_ for _ in ()).throw(RuntimeError("rc")))
    text = "\n".join(lines) + ("\nRESULT OK\n" if ok else "\nRESULT FAIL\n")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    sys.exit(0 if ok else 1)


def main() -> None:
    p = argparse.ArgumentParser(prog="aitree", description="AI Tree Recorder")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--qualita", choices=list(PRESETS))
    common.add_argument("--cattura", choices=["schermo", "finestra"])
    common.add_argument("--lingua")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ui")
    sub.add_parser("auto", parents=[common])
    r = sub.add_parser("record", parents=[common])
    r.add_argument("--solo-registra", action="store_true", help="non trascrivere a fine call")
    f = sub.add_parser("finalize", parents=[common]); f.add_argument("cartella")
    z = sub.add_parser("zoom", parents=[common]); z.add_argument("cartella"); z.add_argument("--zoom")
    l = sub.add_parser("llm"); l.add_argument("cartella")
    l.add_argument("--invia", choices=["claude", "openai", "gemini"])
    l.add_argument("--apri", choices=["claude", "chatgpt", "gemini"])
    l.add_argument("--modello")
    t = sub.add_parser("telefono", parents=[common], help="trascrive le registrazioni dell'app Android")
    t.add_argument("cartella", nargs="?")
    t.add_argument("--resta", action="store_true", help="resta in attesa di nuovi file (controllo ogni minuto)")
    sub.add_parser("config")
    sub.add_parser("devices")
    st = sub.add_parser("selftest"); st.add_argument("out", nargs="?")
    args = p.parse_args()
    cfg = _apply_overrides(config_mod.load(), args)
    {"ui": cmd_ui, "auto": cmd_auto, "record": cmd_record, "finalize": cmd_finalize, "zoom": cmd_zoom,
     "llm": cmd_llm, "telefono": cmd_phone, "config": cmd_config, "devices": cmd_devices, "selftest": cmd_selftest}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
