"""Motore della registrazione, condiviso da riga di comando e interfaccia.

Un thread in background: in modalità automatica aspetta che un'app di call
prenda il microfono; registra; a fine call prepara i file e torna in attesa.
"""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path

from .config import Config


class Controller:
    def __init__(self, cfg: Config, log=print):
        self.cfg = cfg
        self.log = log
        self.auto = False
        self.state = "attesa"          # attesa | registrazione | elaborazione
        self.app: str | None = None
        self.started = 0.0
        self.levels = (0.0, 0.0)
        self.last_folder: Path | None = None
        self._manual_start = threading.Event()
        self._stop = threading.Event()
        self._quit = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    # ── comandi ──
    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def record_now(self) -> None:
        if self.state == "attesa":
            self._manual_start.set()

    def stop_recording(self) -> None:
        self._stop.set()

    def quit(self) -> None:
        self._quit.set()
        self._stop.set()

    @property
    def elapsed(self) -> float:
        return time.time() - self.started if self.state == "registrazione" else 0.0

    # ── ciclo ──
    def _loop(self) -> None:
        from .detect import active_call_app, main_window_of

        seen = 0
        while not self._quit.is_set():
            manual = self._manual_start.is_set()
            app = active_call_app(self.cfg.call_apps) if (self.auto or manual) else None
            seen = seen + 1 if app else 0
            if not manual and not (self.auto and seen >= 2):
                self._quit.wait(2)
                continue
            self._manual_start.clear()
            seen = 0
            try:
                window = main_window_of(app) if (app and self.cfg.capture == "finestra") else None
                self._record(app, window, auto_stop=not manual)
            except Exception as exc:
                self.log(f"Errore: {exc}")
                self.log(traceback.format_exc(limit=3))
            finally:
                self.state = "attesa"
                self.app = None

    def _record(self, app: str | None, window: str | None, auto_stop: bool) -> None:
        from .detect import active_call_app
        from .session import finalize, record_call
        from .zoom import latest_zoom_folder

        self._stop.clear()
        self.app = app
        self.state = "registrazione"
        self.started = time.time()
        self.log(f"● Registrazione avviata" + (f" ({app})" if app else "")
                 + (f" · finestra «{window}»" if window else ""))
        gone = {"n": 0, "last": 0.0}

        def should_stop() -> bool:
            if self._stop.is_set():
                return True
            if not auto_stop:
                return False
            now = time.time()
            if now - gone["last"] < 2:
                return False
            gone["last"] = now
            gone["n"] = 0 if active_call_app(self.cfg.call_apps) else gone["n"] + 1
            return gone["n"] >= 4  # microfono rilasciato da ~8 secondi

        def tick(_elapsed, mic, sys_):
            self.levels = (mic, sys_)

        folder = record_call(self.cfg, app=app, window_title=window, should_stop=should_stop, on_tick=tick)
        self.last_folder = folder
        self.state = "elaborazione"
        self.log(f"■ Registrazione fermata dopo {int(time.time() - self.started) // 60} min. Preparo i file...")
        zoom_dir = None
        if app and "zoom" in app:
            self._quit.wait(20)  # Zoom converte la registrazione locale alla chiusura
            zoom_dir = latest_zoom_folder(self.started)
        finalize(folder, self.cfg, zoom_folder=zoom_dir)
        self.log(f"✓ Pronto: {folder}")
