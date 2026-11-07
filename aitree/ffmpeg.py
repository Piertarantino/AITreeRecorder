"""Video con ffmpeg: cattura schermo/finestra, scelta encoder, unione finale.

Il video viene registrato senza audio in un MKV (resiste a crash e interruzioni).
A fine call viene unito alle due tracce audio in un MP4 con:
  traccia audio 1  "Mix"                 (quella che senti aprendo il file)
  traccia audio 2  "Io - microfono"
  traccia audio 3  "Loro - audio PC"
tutte in Opus mono, il codec pensato per la voce.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import Preset

IS_MAC = sys.platform == "darwin"
HW_ENCODERS = ["h264_videotoolbox"] if IS_MAC else ["h264_nvenc", "h264_qsv", "h264_amf"]
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # niente finestre nere di ffmpeg


def find_ffmpeg(name: str = "ffmpeg") -> str:
    exe = name + (".exe" if sys.platform == "win32" else "")
    here = Path(__file__).resolve().parent.parent
    bundle = Path(getattr(sys, "_MEIPASS", here))  # app impacchettata (installer)
    for cand in (bundle / "bin" / exe, here / "bin" / exe, here / exe):
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if found:
        return found
    try:  # pip install imageio-ffmpeg porta con sé un ffmpeg
        import imageio_ffmpeg
        if name == "ffmpeg":
            return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    raise FileNotFoundError(
        "ffmpeg non trovato. Installalo con:  winget install Gyan.FFmpeg  "
        "oppure metti ffmpeg.exe e ffprobe.exe nella cartella bin\\ del programma.")


def _run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, creationflags=_NO_WINDOW, **kw)


_encoder_cache: str | None = None


def opus_args(kbps: int) -> list[str]:
    """libopus se c'è; altrimenti l'encoder Opus interno di ffmpeg (solo 48 kHz)."""
    listed = _run([find_ffmpeg(), "-hide_banner", "-encoders"]).stdout
    if "libopus" in listed:
        return ["-c:a", "libopus", "-b:a", f"{kbps}k", "-application", "voip"]
    return ["-c:a", "opus", "-strict", "-2", "-b:a", f"{max(kbps, 32)}k", "-ar", "48000"]


def pick_encoder() -> str:
    """Primo encoder hardware che funziona davvero, altrimenti libx264 (CPU)."""
    global _encoder_cache
    if _encoder_cache:
        return _encoder_cache
    ff = find_ffmpeg()
    listed = _run([ff, "-hide_banner", "-encoders"]).stdout
    for enc in HW_ENCODERS:
        if enc not in listed:
            continue
        # Elencato non basta: prova a codificare un fotogramma.
        test = _run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                     "color=black:s=640x360:d=0.2", "-vf", "format=nv12", "-c:v", enc,
                     "-f", "null", "-"], timeout=20)
        if test.returncode == 0:
            _encoder_cache = enc
            return enc
    _encoder_cache = "libx264"
    return _encoder_cache


def encoder_args(enc: str, p: Preset) -> list[str]:
    rate = ["-maxrate", f"{p.max_kbps}k", "-bufsize", f"{p.max_kbps * 2}k"]
    gop = ["-g", str(max(p.fps, 1) * 10)]
    if enc == "h264_nvenc":
        return ["-c:v", enc, "-preset", "p4", "-rc", "vbr", "-cq", str(p.quality), "-b:v", "0", *rate, *gop]
    if enc == "h264_qsv":
        return ["-c:v", enc, "-global_quality", str(p.quality), *gop]
    if enc == "h264_videotoolbox":  # chip Apple / Intel Quick Sync del Mac
        return ["-c:v", enc, "-b:v", f"{max(150, p.max_kbps // 3)}k", *rate, *gop, "-realtime", "1"]
    if enc == "h264_amf":
        return ["-c:v", enc, "-rc", "cqp", "-qp_i", str(p.quality), "-qp_p", str(p.quality + 2), *gop]
    return ["-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
            "-crf", str(p.quality), *rate, *gop]


def video_filter(enc: str, p: Preset) -> str:
    pix = "yuv420p" if enc == "libx264" else "nv12"
    if p.max_width:
        return f"scale=w='trunc(min({p.max_width},iw)/2)*2':h=-2,format={pix}"
    return f"scale=w='trunc(iw/2)*2':h='trunc(ih/2)*2',format={pix}"


def mac_screen_index() -> str:
    """Indice avfoundation del primo schermo ("Capture screen 0")."""
    r = _run([find_ffmpeg(), "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""])
    for line in (r.stderr or "").splitlines():
        if "Capture screen" in line and "[" in line:
            return line.rsplit("[", 1)[-1].split("]", 1)[0].strip()
    return "1"


class VideoRecorder:
    """Avvia ffmpeg in background; stop() lo chiude in modo pulito (tasto q)."""

    def __init__(self, out: Path, preset: Preset, window_title: str | None = None,
                 source_args: list[str] | None = None):
        self.out = out
        self.preset = preset
        self.window_title = window_title
        self.source_args = source_args  # per i test fuori da Windows
        self.proc: subprocess.Popen | None = None
        self.encoder = ""
        self.log = out.with_suffix(".log")

    def start(self) -> None:
        ff = find_ffmpeg()
        self.encoder = pick_encoder()
        p = self.preset
        if self.source_args:
            src = self.source_args
        elif IS_MAC:  # schermo principale; la cattura per finestra non esiste in avfoundation
            src = ["-f", "avfoundation", "-capture_cursor", "1", "-framerate", str(p.fps),
                   "-i", f"{mac_screen_index()}:none"]
        else:
            src = ["-f", "gdigrab", "-framerate", str(p.fps), "-draw_mouse", "1",
                   "-i", f"title={self.window_title}" if self.window_title else "desktop"]
        # I timestamp del video sono l'ora reale: così a fine call si allinea all'audio.
        args = [ff, "-hide_banner", "-loglevel", "warning", "-y",
                "-use_wallclock_as_timestamps", "1", "-thread_queue_size", "64", *src,
                "-vf", video_filter(self.encoder, p), "-fps_mode", "vfr",
                *encoder_args(self.encoder, p), "-copyts", "-an", str(self.out)]
        self._logf = open(self.log, "w", encoding="utf-8")
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=self._logf, creationflags=_NO_WINDOW)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, timeout: float = 15) -> None:
        if not self.proc:
            return
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write(b"q")
                self.proc.stdin.flush()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self._logf.close()


def probe_start(path: Path) -> float | None:
    """Ora reale (epoch) del primo fotogramma, se presente nel file."""
    try:
        out = _run([find_ffmpeg("ffprobe"), "-v", "error", "-show_entries", "format=start_time",
                    "-of", "json", str(path)]).stdout
        st = float(json.loads(out)["format"]["start_time"])
        return st if st > 1e9 else None
    except Exception:
        return None


def has_video(path: Path) -> bool:
    try:
        out = _run([find_ffmpeg("ffprobe"), "-v", "error", "-select_streams", "v",
                    "-show_entries", "stream=index", "-of", "csv=p=0", str(path)]).stdout
        return bool(out.strip())
    except Exception:
        return False


MAX_PEOPLE = 16


def mux(folder: Path, preset: Preset, audio_epoch: float, title: str,
        people: list[tuple[str, Path]] | None = None) -> Path:
    """Unisce video + mic.wav + system.wav (+ una traccia per persona, max 16) in call.mp4.

    Tracce audio: Mix, Io, Loro, poi una per ogni persona (Zoom o separazione per voce).
    """
    ff = find_ffmpeg()
    out = folder / "call.mp4"
    prev = folder / "call-precedente.mp4"
    if out.exists():                      # rifacimento: il video si prende dal vecchio MP4
        out.replace(prev)
    video = folder / "video.mkv"
    args = [ff, "-hide_banner", "-loglevel", "error", "-y"]
    use_video = False
    if video.exists() and video.stat().st_size > 0 and has_video(video):
        start = probe_start(video)
        offset = (start - audio_epoch) if start else 0.0
        args += ["-itsoffset", f"{offset:.3f}", "-i", str(video)]
        use_video = True
    elif prev.exists() and has_video(prev):
        args += ["-i", str(prev)]
        use_video = True
    people = (people or [])[:MAX_PEOPLE]
    a0 = 1 if use_video else 0
    args += ["-i", str(folder / "mic.wav"), "-i", str(folder / "system.wav")]
    for _name, wav in people:
        args += ["-i", str(wav)]
    args += ["-filter_complex",
             f"[{a0}:a][{a0 + 1}:a]amix=inputs=2:duration=longest:normalize=0,"
             f"alimiter=limit=0.95[mix]"]
    if use_video:
        args += ["-map", "0:v", "-c:v", "copy"]
    args += ["-map", "[mix]", "-map", f"{a0}:a", "-map", f"{a0 + 1}:a"]
    for i in range(len(people)):
        args += ["-map", f"{a0 + 2 + i}:a"]
    names = ["Mix", "Io - microfono", "Loro - audio PC"] + [n for n, _ in people]
    disp: list[str] = []
    for i in range(len(names)):
        disp += [f"-disposition:a:{i}", "default" if i == 0 else "0"]
    args += [*opus_args(preset.opus_kbps), "-ac", "1",
             "-metadata", f"title={title}", *_track_names(names),
             "-metadata:s:a:0", "language=ita", *disp,
             "-movflags", "+faststart", str(out)]
    r = _run(args)
    if r.returncode != 0:
        if prev.exists() and not out.exists():
            prev.replace(out)
        raise RuntimeError("Unione con ffmpeg non riuscita: " + r.stderr[-800:])
    video.unlink(missing_ok=True)
    (folder / "video.log").unlink(missing_ok=True)
    prev.unlink(missing_ok=True)
    return out


def decode_mono(src: Path, dst: Path, rate: int = 16000) -> None:
    r = _run([find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
              "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", str(dst)])
    if r.returncode != 0:
        raise RuntimeError(f"Decodifica di {src.name} non riuscita: {r.stderr[-300:]}")


def _track_names(names: list[str]) -> list[str]:
    # I player leggono il nome della traccia da "title" (MKV) o "handler_name" (MP4).
    out: list[str] = []
    for i, n in enumerate(names):
        out += [f"-metadata:s:a:{i}", f"title={n}", f"-metadata:s:a:{i}", f"handler_name={n}"]
    return out


def extract_tracks(mp4: Path, folder: Path) -> None:
    """Ricava mic.wav e system.wav da un call.mp4 già unito (per ritrascrivere)."""
    ff = find_ffmpeg()
    for idx, name in ((1, "mic.wav"), (2, "system.wav")):
        _run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp4),
              "-map", f"0:a:{idx}", "-ac", "1", "-ar", "16000", str(folder / name)])
