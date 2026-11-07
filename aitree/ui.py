"""Interfaccia leggera: finestra tkinter + icona vicino all'orologio (pystray).

  pythonw -m aitree ui      (senza finestra nera del terminale)

Chiudendo la finestra il programma resta nell'area di notifica e continua a
registrare in automatico; si esce dal menu dell'icona.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import config as config_mod
from .config import PRESETS
from .controller import Controller
from .session import DISCLAIMER

STATE_LABEL = {"attesa": "In attesa di una call", "registrazione": "● REGISTRAZIONE",
               "elaborazione": "Preparo trascrizione e report..."}
CHATS = {"Claude": "claude", "ChatGPT": "chatgpt", "Gemini": "gemini"}
GPU_CODES = {"automatica": "auto", "NVIDIA": "nvidia", "no (CPU)": "cpu"}
GPU_LABELS = {v: k for k, v in GPU_CODES.items()}


class _QueueWriter:
    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s: str) -> None:
        if s:
            self.q.put(("log", s))

    def flush(self) -> None:
        pass


def _open(path: Path) -> None:
    if not path.exists():
        messagebox.showinfo("AI Tree Recorder", f"File non trovato:\n{path}")
        return
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - apre con il programma predefinito
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App:
    def __init__(self) -> None:
        self.cfg = config_mod.load()
        self.q: queue.Queue = queue.Queue()
        sys.stdout = sys.stderr = _QueueWriter(self.q)
        self.ctl = Controller(self.cfg, log=lambda s: self.q.put(("log", s + "\n")))
        self.ctl.auto = True
        self.tray = None

        self.root = tk.Tk()
        self.root.title("AI Tree Recorder")
        self.root.geometry("780x680")
        self.root.minsize(640, 520)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build()
        self._log(DISCLAIMER)
        self.refresh_calls()
        self.ctl.start()
        self._start_tray()
        self.root.after(250, self._poll)
        self.root.after(5000, self._check_phone)

    # ── costruzione ──
    def _build(self) -> None:
        pad = {"padx": 10, "pady": 4}
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        self.status = ttk.Label(top, text="", font=("Segoe UI", 14, "bold"))
        self.status.pack(side="left")
        self.timer = ttk.Label(top, text="", font=("Segoe UI", 12))
        self.timer.pack(side="right")

        lv = ttk.Frame(self.root)
        lv.pack(fill="x", **pad)
        ttk.Label(lv, text="Io").grid(row=0, column=0, sticky="w")
        self.lv_mic = ttk.Progressbar(lv, maximum=100, length=250)
        self.lv_mic.grid(row=0, column=1, padx=6)
        ttk.Label(lv, text="Loro").grid(row=0, column=2, sticky="w", padx=(16, 0))
        self.lv_sys = ttk.Progressbar(lv, maximum=100, length=250)
        self.lv_sys.grid(row=0, column=3, padx=6)

        ctl = ttk.Frame(self.root)
        ctl.pack(fill="x", **pad)
        self.btn_rec = ttk.Button(ctl, text="● Registra ora", command=self.ctl.record_now)
        self.btn_rec.pack(side="left")
        self.btn_stop = ttk.Button(ctl, text="■ Ferma", command=self.ctl.stop_recording)
        self.btn_stop.pack(side="left", padx=6)
        self.var_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctl, text="Registra da solo quando inizia una call", variable=self.var_auto,
                        command=self._set_auto).pack(side="left", padx=12)

        opt = ttk.LabelFrame(self.root, text="Impostazioni")
        opt.pack(fill="x", **pad)
        self.var_q = tk.StringVar(value=self.cfg.quality)
        self.var_c = tk.StringVar(value=self.cfg.capture)
        self.var_l = tk.StringVar(value=self.cfg.language)
        self.var_name = tk.StringVar(value=self.cfg.my_name)
        for col, (lab, var, vals, w) in enumerate((
                ("Qualità", self.var_q, list(PRESETS), 9),
                ("Cattura", self.var_c, ["schermo", "finestra"], 9),
                ("Lingua", self.var_l, ["it", "en", "auto"], 5))):
            ttk.Label(opt, text=lab).grid(row=0, column=col * 2, padx=(8, 2), pady=6, sticky="e")
            cb = ttk.Combobox(opt, textvariable=var, values=vals, width=w, state="readonly")
            cb.grid(row=0, column=col * 2 + 1, sticky="w")
            cb.bind("<<ComboboxSelected>>", lambda _e: self._save_settings())
        ttk.Label(opt, text="Il tuo nome").grid(row=0, column=6, padx=(12, 2), sticky="e")
        e = ttk.Entry(opt, textvariable=self.var_name, width=14)
        e.grid(row=0, column=7, sticky="w", padx=(0, 8))
        e.bind("<FocusOut>", lambda _e: self._save_settings())
        ttk.Label(opt, text="GPU").grid(row=1, column=0, padx=(8, 2), pady=(0, 6), sticky="e")
        self.var_gpu = tk.StringVar(value=GPU_LABELS.get(self.cfg.gpu, "automatica"))
        gcb = ttk.Combobox(opt, textvariable=self.var_gpu, values=list(GPU_CODES), width=9, state="readonly")
        gcb.grid(row=1, column=1, sticky="w", pady=(0, 6))
        gcb.bind("<<ComboboxSelected>>", lambda _e: self._gpu_changed())
        self.lbl_gpu = ttk.Label(opt, text="", foreground="#555")
        self.lbl_gpu.grid(row=1, column=2, columnspan=6, sticky="w", padx=8, pady=(0, 6))
        self.lbl_preset = ttk.Label(opt, text=self.cfg.preset.label, foreground="#555")
        self.lbl_preset.grid(row=2, column=0, columnspan=8, sticky="w", padx=8, pady=(0, 6))
        threading.Thread(target=self._detect_gpu, daemon=True).start()

        calls = ttk.LabelFrame(self.root, text="Call registrate")
        calls.pack(fill="both", expand=True, **pad)
        cols = ("data", "app", "durata", "tracce")
        self.tree = ttk.Treeview(calls, columns=cols, show="headings", height=7, selectmode="browse")
        for c, lab, w in (("data", "Data", 150), ("app", "App", 90), ("durata", "Durata", 70),
                          ("tracce", "Persone / stato", 300)):
            self.tree.heading(c, text=lab)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=6, pady=(6, 2))
        self.tree.bind("<Double-1>", lambda _e: self._open_sel("call.mp4"))

        acts = ttk.Frame(calls)
        acts.pack(fill="x", padx=6, pady=6)
        for lab, fn in (("Video", "call.mp4"), ("Report", "report.md"),
                        ("Trascrizione", "trascrizione.md"), ("Cartella", "")):
            ttk.Button(acts, text=lab, command=lambda f=fn: self._open_sel(f)).pack(side="left", padx=(0, 4))
        self.var_chat = tk.StringVar(value="Claude")
        ttk.Button(acts, text="Apri in", command=self._open_chat).pack(side="left", padx=(12, 2))
        ttk.Combobox(acts, textvariable=self.var_chat, values=list(CHATS), width=8,
                     state="readonly").pack(side="left")
        if self.cfg.llm.provider:
            ttk.Button(acts, text="Riassunto IA", command=self._summary).pack(side="left", padx=(8, 0))
        ttk.Button(acts, text="Tracce Zoom", command=self._zoom).pack(side="left", padx=(8, 0))
        ttk.Button(acts, text="↻", width=3, command=self.refresh_calls).pack(side="right")

        logf = ttk.LabelFrame(self.root, text="Messaggi")
        logf.pack(fill="both", **pad)
        self.logbox = tk.Text(logf, height=8, wrap="word", font=("Consolas", 9), state="disabled")
        self.logbox.pack(fill="both", expand=True, padx=6, pady=6)

    # ── aggiornamento periodico ──
    def _poll(self) -> None:
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self._log(data)
                elif kind == "cmd":
                    data()
        except queue.Empty:
            pass
        st = self.ctl.state
        self.status.configure(text=STATE_LABEL.get(st, st) + (f" · {self.ctl.app}" if self.ctl.app else ""),
                              foreground="#b00020" if st == "registrazione" else "")
        e = int(self.ctl.elapsed)
        self.timer.configure(text=f"{e // 3600}:{e % 3600 // 60:02}:{e % 60:02}" if e else "")
        mic, sys_ = self.ctl.levels if st == "registrazione" else (0, 0)
        self.lv_mic["value"] = min(100, mic * 200)
        self.lv_sys["value"] = min(100, sys_ * 200)
        self.btn_rec.state(["!disabled"] if st == "attesa" else ["disabled"])
        self.btn_stop.state(["!disabled"] if st == "registrazione" else ["disabled"])
        if getattr(self, "_last_state", None) == "elaborazione" and st == "attesa":
            self.refresh_calls()
        self._last_state = st
        if self.tray:
            self.tray.icon = self._icon_image(st == "registrazione")
        self.root.after(250, self._poll)

    def _log(self, s: str) -> None:
        self.logbox.configure(state="normal")
        self.logbox.insert("end", s)
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    # ── registrazioni dal telefono (app Android → cartella Drive) ──
    def _check_phone(self) -> None:
        inbox = Path(self.cfg.phone_inbox) if self.cfg.phone_inbox else None
        busy = getattr(self, "_phone_busy", False)
        if inbox and inbox.is_dir() and not busy and self.ctl.state == "attesa":
            from .phone import pending, process
            files = pending(self.cfg, inbox)
            if files:
                self._phone_busy = True

                def job():
                    try:
                        for f in files:
                            if self.ctl.state != "attesa":
                                break  # una call ha la precedenza: riprende al prossimo controllo
                            print(f"Registrazione dal telefono: {f.name}")
                            try:
                                process(f, self.cfg)
                            except Exception as exc:
                                print(f"  {f.name}: non elaborato ({exc})")
                    finally:
                        self._phone_busy = False
                        self.q.put(("cmd", self.refresh_calls))
                threading.Thread(target=job, daemon=True).start()
        self.root.after(60_000, self._check_phone)

    # ── impostazioni ──
    def _set_auto(self) -> None:
        self.ctl.auto = self.var_auto.get()

    # ── GPU NVIDIA ──
    def _detect_gpu(self) -> None:
        from . import gpu
        if sys.platform == "darwin":
            text = "Mac: trascrizione sul processore (chip Apple)"
        elif not gpu.has_nvidia():
            text = "Nessuna scheda NVIDIA trovata: si usa il processore"
        elif gpu.libs_ready():
            text = f"{gpu.gpu_name()}: pronta, trascrizione veloce"
        else:
            text = f"{gpu.gpu_name()} trovata: scegli NVIDIA per scaricare il supporto (~1,2 GB, una volta)"
        self.q.put(("cmd", lambda: self.lbl_gpu.configure(text=text)))

    def _gpu_changed(self) -> None:
        from . import gpu
        self.cfg.gpu = GPU_CODES[self.var_gpu.get()]
        config_mod.save(self.cfg)
        if self.cfg.gpu != "nvidia" or sys.platform != "win32":
            return
        if not gpu.has_nvidia():
            messagebox.showinfo("AI Tree Recorder", "Non trovo una scheda NVIDIA con driver installati. "
                                "La trascrizione userà il processore.")
            return
        if gpu.libs_ready() or getattr(self, "_gpu_downloading", False):
            return
        if not messagebox.askyesno("AI Tree Recorder", "Per usare la scheda NVIDIA servono le librerie CUDA "
                                   "(circa 1,2 GB, da scaricare una volta sola). Scaricarle adesso?"):
            return
        self._gpu_downloading = True

        def job():
            try:
                gpu.download(progress=lambda m: print(m))
            finally:
                self._gpu_downloading = False
                self._detect_gpu()
        threading.Thread(target=job, daemon=True).start()

    def _save_settings(self) -> None:
        self.cfg.quality, self.cfg.capture = self.var_q.get(), self.var_c.get()
        self.cfg.language, self.cfg.my_name = self.var_l.get(), self.var_name.get().strip()
        self.lbl_preset.configure(text=self.cfg.preset.label)
        config_mod.save(self.cfg)

    # ── elenco call ──
    def refresh_calls(self) -> None:
        self.tree.delete(*self.tree.get_children())
        root = Path(self.cfg.output_dir)
        metas = sorted(root.glob("*/*/meta.json"), key=lambda p: p.parent.name, reverse=True)[:200]
        for m in metas:
            try:
                meta = json.loads(m.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            d = int(meta.get("duration_s", 0))
            people = meta.get("audio_tracks", [])[3:]
            info = ", ".join(people) if people else ("pronta" if meta.get("finalized") else "da completare")
            n = m.parent.name
            when = f"{n[8:10]}/{n[5:7]}/{n[0:4]} {n[11:13]}:{n[14:16]}" if len(n) >= 16 else n
            self.tree.insert("", "end", iid=str(m.parent), values=(
                when, meta.get("app", ""),
                f"{d // 60} min", info))

    def _sel(self) -> Path | None:
        s = self.tree.selection()
        if not s:
            messagebox.showinfo("AI Tree Recorder", "Seleziona prima una call dall'elenco.")
            return None
        return Path(s[0])

    def _open_sel(self, name: str) -> None:
        f = self._sel()
        if f:
            _open(f / name if name else f)

    def _open_chat(self) -> None:
        from .llm import open_chat
        f = self._sel()
        if f:
            self._log(open_chat(CHATS[self.var_chat.get()], f / "pacchetto-llm.md") + "\n")

    def _background(self, label: str, fn) -> None:
        def run():
            try:
                fn()
            except Exception as exc:
                print(f"{label}: {exc}")
            self.q.put(("cmd", self.refresh_calls))
        threading.Thread(target=run, daemon=True).start()

    def _summary(self) -> None:
        from .llm import send
        f = self._sel()
        if not f:
            return

        def job():
            print(f"Invio a {self.cfg.llm.provider}...")
            out = send(self.cfg.llm.provider, (f / "pacchetto-llm.md").read_text(encoding="utf-8"),
                       self.cfg.llm.api_key, self.cfg.llm.model)
            (f / "riassunto-ia.md").write_text(out, encoding="utf-8")
            print("Riassunto salvato.")
            self.q.put(("cmd", lambda: _open(f / "riassunto-ia.md")))
        self._background("Riassunto IA", job)

    def _zoom(self) -> None:
        from tkinter import filedialog

        from .session import finalize
        from .zoom import find_tracks
        f = self._sel()
        if not f:
            return
        z = filedialog.askdirectory(title="Cartella della registrazione Zoom",
                                    initialdir=str(Path.home() / "Documents" / "Zoom"))
        if not z:
            return
        if not find_tracks(Path(z)):
            messagebox.showinfo("AI Tree Recorder", "In quella cartella non ci sono tracce per persona di Zoom.")
            return
        self._background("Tracce Zoom", lambda: finalize(f, self.cfg, zoom_folder=Path(z), send_llm=False))

    # ── icona nell'area di notifica ──
    @staticmethod
    def _icon_image(recording: bool):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((6, 6, 58, 58), fill=(200, 30, 30) if recording else (70, 110, 70))
        d.ellipse((22, 22, 42, 42), fill=(255, 255, 255))
        return img

    def _start_tray(self) -> None:
        if sys.platform == "darwin":
            return  # su Mac l'icona di sistema non convive con tkinter: si usa la finestra
        try:
            import pystray
        except ImportError:
            return  # senza pystray si usa solo la finestra
        cmd = lambda fn: (lambda _icon, _item: self.q.put(("cmd", fn)))
        menu = pystray.Menu(
            pystray.MenuItem("Mostra", cmd(self.show), default=True),
            pystray.MenuItem("Registra ora", cmd(self.ctl.record_now)),
            pystray.MenuItem("Ferma", cmd(self.ctl.stop_recording)),
            pystray.MenuItem("Esci", cmd(self.quit)),
        )
        self.tray = pystray.Icon("aitree", self._icon_image(False), "AI Tree Recorder", menu)
        self.tray.run_detached()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def on_close(self) -> None:
        if self.tray:
            self.root.withdraw()  # resta attivo vicino all'orologio
        else:
            self.quit()

    def quit(self) -> None:
        if self.ctl.state != "attesa" and not messagebox.askyesno(
                "AI Tree Recorder", "C'è una registrazione o un'elaborazione in corso. Uscire comunque?"):
            return
        self.ctl.quit()
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App().run()
