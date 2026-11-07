"""GPU NVIDIA: rilevamento e supporto CUDA scaricato su richiesta (solo Windows).

L'installer non include le librerie CUDA (oltre 1 GB): se c'è una scheda NVIDIA
l'utente può scaricarle una volta dall'interfaccia. Vengono prese dai pacchetti
ufficiali NVIDIA su PyPI e messe in %APPDATA%\\AI-TREE\\cuda.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .config import CONFIG_DIR

CUDA_DIR = CONFIG_DIR / "cuda"
PACKAGES = [("nvidia-cublas-cu12", "12."), ("nvidia-cudnn-cu12", "9.")]
_added = False


def has_nvidia() -> bool:
    """C'è una scheda NVIDIA con driver? (nvidia-smi arriva col driver)."""
    if sys.platform == "darwin":
        return False
    smi = shutil.which("nvidia-smi") or (
        r"C:\Windows\System32\nvidia-smi.exe" if os.path.exists(r"C:\Windows\System32\nvidia-smi.exe") else None)
    if not smi:
        return False
    try:
        r = subprocess.run([smi, "-L"], capture_output=True, text=True, timeout=10,
                           creationflags=0x08000000 if sys.platform == "win32" else 0)
        return r.returncode == 0 and "GPU" in r.stdout
    except Exception:
        return False


def gpu_name() -> str:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=10,
                           creationflags=0x08000000 if sys.platform == "win32" else 0)
        return r.stdout.strip().splitlines()[0]
    except Exception:
        return "NVIDIA"


def libs_ready() -> bool:
    """Le librerie CUDA ci sono (scaricate da noi, o installate con pip in un ambiente Python)."""
    if any(CUDA_DIR.glob("cublas64_*.dll")) and any(CUDA_DIR.glob("cudnn*64_9.dll")):
        return True
    if not getattr(sys, "frozen", False):
        try:
            import nvidia.cublas  # noqa: F401  (pip install nvidia-cublas-cu12 ...)
            import nvidia.cudnn  # noqa: F401
            return True
        except ImportError:
            pass
    return False


def enable() -> None:
    """Rende visibili le DLL CUDA a ctranslate2. Va chiamata prima di caricare il modello."""
    global _added
    if _added or sys.platform != "win32":
        return
    dirs = [CUDA_DIR]
    try:
        import nvidia.cublas
        import nvidia.cudnn
        dirs += [Path(nvidia.cublas.__path__[0]) / "bin", Path(nvidia.cudnn.__path__[0]) / "bin"]
    except ImportError:
        pass
    for d in dirs:
        if d.is_dir():
            os.add_dll_directory(str(d))
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
    _added = True


def _latest_wheel(package: str, major: str) -> tuple[str, int]:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=30) as r:
        rel = json.load(r)["releases"]

    def key(v):
        return [int(p) for p in v.split(".") if p.isdigit()]

    for v in sorted((v for v in rel if v.startswith(major)), key=key, reverse=True):
        for f in rel[v]:
            if f["filename"].endswith("win_amd64.whl"):
                return f["url"], f["size"]
    raise RuntimeError(f"Pacchetto {package} per Windows non trovato.")


def download(progress=print) -> None:
    """Scarica cuBLAS e cuDNN (~1,2 GB) ed estrae solo le DLL."""
    if sys.platform != "win32":
        raise RuntimeError("Il supporto GPU scaricabile è solo per Windows.")
    CUDA_DIR.mkdir(parents=True, exist_ok=True)
    for package, major in PACKAGES:
        url, size = _latest_wheel(package, major)
        progress(f"Scarico {package} ({size / 1e6:.0f} MB)...")
        with tempfile.TemporaryDirectory() as tmp:
            whl = Path(tmp) / "pkg.whl"
            with urllib.request.urlopen(url, timeout=60) as r, open(whl, "wb") as out:
                done, step = 0, 0
                while chunk := r.read(1 << 20):
                    out.write(chunk)
                    done += len(chunk)
                    if done * 10 // size > step:
                        step = done * 10 // size
                        progress(f"  {package}: {step * 10}%")
            with zipfile.ZipFile(whl) as z:
                for name in z.namelist():
                    if name.lower().endswith(".dll"):
                        (CUDA_DIR / Path(name).name).write_bytes(z.read(name))
    progress("Supporto GPU NVIDIA pronto.")
