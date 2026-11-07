"""Una call dall'inizio alla fine: registrazione, unione, trascrizione, report, pacchetto IA."""
from __future__ import annotations

import json
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from . import ffmpeg
from .config import Config
from .detect import pretty_app
from .transcribe import Segment

DISCLAIMER = """\
──────────────────────────────────────────────────────────────
 AI Tree Recorder · cosa aspettarsi
──────────────────────────────────────────────────────────────
 Separazione "Io" / "Loro": funziona con qualsiasi app di call.
 Persone distinte dentro "Loro":
   Zoom            sì, con un file per persona: attiva in Zoom
                   "Registra un file audio separato per ogni
                   partecipante" (registrazione locale)
   Meet / Teams    no per ora: l'audio degli altri arriva già
                   mixato, quindi restano tutti "Loro"
 Usa le cuffie: con le casse la tua traccia ricapta gli altri.
 Avvisa i partecipanti che stai registrando.
──────────────────────────────────────────────────────────────
"""


def new_folder(cfg: Config, app: str | None) -> Path:
    now = datetime.now()
    return Path(cfg.output_dir) / now.strftime("%Y-%m") / f"{now:%Y-%m-%d_%H-%M}_{pretty_app(app)}"


def check_space(cfg: Config) -> None:
    root = Path(cfg.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(root).free / 1e9
    if free_gb < cfg.min_free_gb:
        raise RuntimeError(f"Spazio libero insufficiente: {free_gb:.1f} GB (minimo {cfg.min_free_gb} GB).")


def record_call(cfg: Config, app: str | None = None, window_title: str | None = None,
                should_stop=None, on_tick=None) -> Path:
    """Registra audio (2 tracce) e, se il preset lo prevede, video. Ritorna la cartella."""
    from .capture import record

    check_space(cfg)
    p = cfg.preset
    folder = new_folder(cfg, app)
    folder.mkdir(parents=True, exist_ok=True)
    video = None
    if p.video:
        title = window_title if cfg.capture == "finestra" else None
        video = ffmpeg.VideoRecorder(folder / "video.mkv", p, window_title=title)
        try:
            video.start()
        except Exception as exc:
            print(f"  Video non avviato ({exc}): registro solo l'audio.")
            video = None

    low_space = threading.Event()

    def stop_check():
        if shutil.disk_usage(folder).free < 0.5e9:
            low_space.set()
            return True
        return bool(should_stop and should_stop())

    try:
        meta = record(folder, should_stop=stop_check, on_tick=on_tick)
    finally:
        if video:
            video.stop()
    meta.update({
        "title": f"{pretty_app(app)} {datetime.fromtimestamp(meta['started_at']):%d/%m/%Y %H:%M}",
        "app": pretty_app(app), "app_process": app or "", "quality": cfg.quality,
        "capture": (("finestra: " + window_title) if (cfg.capture == "finestra" and window_title) else "schermo") if p.video else "solo audio",
        "video_encoder": video.encoder if video else "", "language": cfg.language,
        "stopped_for_low_space": low_space.is_set(),
    })
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def finalize(folder: Path, cfg: Config, zoom_folder: Path | None = None, send_llm: bool | None = None) -> None:
    """Unione MP4, trascrizione, report, pacchetto IA, invii facoltativi."""
    from .llm import build_pack, open_chat, send
    from .merge import merge, to_json, to_markdown, to_srt
    from .report import build_report
    from .transcribe import load_model, transcribe_track
    from .zoom import prepare_tracks as prepare_zoom

    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    mic_wav, sys_wav = folder / "mic.wav", folder / "system.wav"
    mp4 = folder / "call.mp4"

    # 1. Tracce audio di partenza (se il MP4 c'è già e i WAV no, li ricava)
    if not mic_wav.exists() and mp4.exists():
        ffmpeg.extract_tracks(mp4, folder)

    # 2. Tracce per persona: Zoom (un file a testa)
    people: list[tuple[str, Path]] = []
    if zoom_folder:
        print(f"  Tracce per persona di Zoom: {zoom_folder}")
        people, offset = prepare_zoom(zoom_folder, folder, [sys_wav, mic_wav])
        meta["zoom_tracks"] = str(zoom_folder)
        meta["zoom_offset_s"] = round(offset, 2)
        print(f"  {len(people)} persone, allineate con scarto di {offset:+.2f} s")

    # 3. MP4: Mix, Io, Loro + una traccia per persona (max 16)
    if not mp4.exists() or people:
        t = time.time()
        ffmpeg.mux(folder, cfg.preset, meta["started_at"], meta.get("title", "Call"), people)
        print(f"  call.mp4 pronto ({mp4.stat().st_size / 1e6:.0f} MB) in {time.time() - t:.0f} s")
    meta["audio_tracks"] = ["Mix", "Io", "Loro"] + [n for n, _ in people]

    # 4. Trascrizione
    lang = None if cfg.language == "auto" else cfg.language
    me = cfg.my_name or "Io"
    t = time.time()
    model, desc = load_model(mode=cfg.gpu)
    print(f"  Trascrivo con {desc}...")
    mic = transcribe_track(model, mic_wav, me, lang)
    if people:
        others = []
        for name, wav in people:
            if name.lower() == me.lower():
                continue  # la tua traccia Zoom: c'è già il microfono
            print(f"  traccia di {name}...")
            others += transcribe_track(model, wav, name, lang)
    else:
        others = transcribe_track(model, sys_wav, "Loro", lang)
    segs, dropped = merge(mic, others)
    print(f"  {len(segs)} interventi in {time.time() - t:.0f} s"
          + (f" ({dropped} frasi d'eco tolte)" if dropped else ""))

    title = meta.get("title", "Call")
    (folder / "trascrizione.md").write_text(to_markdown(segs, title), encoding="utf-8")
    (folder / "trascrizione.srt").write_text(to_srt(segs), encoding="utf-8")
    (folder / "trascrizione.json").write_text(to_json(segs), encoding="utf-8")

    # 3. Report senza IA
    report = build_report(meta, segs)
    (folder / "report.md").write_text(report, encoding="utf-8")

    # 4. Pacchetto per qualsiasi IA
    pack_text = build_pack(meta, report, transcript_lines(segs), cfg.llm.prompt, me)
    pack = folder / "pacchetto-llm.md"
    pack.write_text(pack_text, encoding="utf-8")
    files = [folder / "report.md", pack]

    # 5. Facoltativi: API, chat nel browser, email
    do_send = cfg.llm.auto_send if send_llm is None else send_llm
    if do_send and cfg.llm.provider:
        try:
            print(f"  Invio a {cfg.llm.provider}...")
            answer = send(cfg.llm.provider, pack_text, cfg.llm.api_key, cfg.llm.model)
            (folder / "riassunto-ia.md").write_text(answer, encoding="utf-8")
            files.insert(0, folder / "riassunto-ia.md")
            print("  Riassunto IA salvato in riassunto-ia.md")
        except Exception as exc:
            print(f"  Invio all'IA non riuscito: {exc}")
    if cfg.llm.open_chat:
        print("  " + open_chat(cfg.llm.open_chat, pack))
    if cfg.email.enabled:
        from .emailer import send_report
        try:
            body = (folder / "riassunto-ia.md").read_text(encoding="utf-8") if (folder / "riassunto-ia.md").exists() else report
            send_report(cfg.email, f"Call: {title}", body,
                        [folder / "trascrizione.md"] if cfg.email.attach_transcript else [])
            print("  Report inviato per email.")
        except Exception as exc:
            print(f"  Email non inviata: {exc}")

    # 6. Pulizia: i WAV servono solo per la trascrizione
    if not cfg.keep_wav and mp4.exists():
        mic_wav.unlink(missing_ok=True)
        sys_wav.unlink(missing_ok=True)
        shutil.rmtree(folder / "persone", ignore_errors=True)
    meta["finalized"] = True
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"■ Pronto: {folder}")


def transcript_lines(segs: list[Segment]) -> list[str]:
    out = []
    for s in segs:
        m, sec = divmod(int(s.start), 60)
        h, m = divmod(m, 60)
        ts = f"{h}:{m:02}:{sec:02}" if h else f"{m:02}:{sec:02}"
        out.append(f"[{ts}] {s.speaker}: {s.text}")
    return out
