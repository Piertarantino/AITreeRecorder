"""Rilevamento della call senza estensioni e senza IA (solo Windows).

Windows annota nel registro quale programma sta usando il microfono:
  HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone
Una voce con LastUsedTimeStop = 0 significa "microfono in uso adesso".
Quando Zoom, Teams o il browser prendono il microfono la call è iniziata;
quando lo rilasciano è finita. Funziona con qualsiasi app, browser o desktop.
"""
from __future__ import annotations

import os
import sys

MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def _mac_mic_users() -> list[str]:
    """Su Mac: bundle id delle app che usano il microfono (Core Audio, macOS 14+), escluso noi."""
    import subprocess

    from .capture import helper_path
    try:
        out = subprocess.run([helper_path(), "mic-users"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    mine = {os.getpid()}
    apps = []
    for line in out.splitlines():
        pid, _, name = line.partition("\t")
        if pid.isdigit() and int(pid) in mine:
            continue
        name = name.lower()
        if "python" in name or "aitree" in name:
            continue
        apps.append(name)
    return apps


def apps_using_mic() -> list[str]:
    """Nomi (in minuscolo) delle app che stanno usando il microfono adesso."""
    if sys.platform == "darwin":
        return _mac_mic_users()
    if sys.platform != "win32":
        return []
    import winreg

    found: list[str] = []

    def scan(path: str) -> None:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return
        with key:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                if name == "NonPackaged":
                    continue
                try:
                    with winreg.OpenKey(key, name) as sub:
                        stop, _ = winreg.QueryValueEx(sub, "LastUsedTimeStop")
                        start, _ = winreg.QueryValueEx(sub, "LastUsedTimeStart")
                except OSError:
                    continue
                if stop == 0 and start:
                    # NonPackaged: "C:#Program Files#Zoom#bin#Zoom.exe"; app Store: "MSTeams_8wekyb3d8bbwe"
                    found.append(name.replace("#", "\\").split("\\")[-1].lower())

    scan(MIC_KEY)
    scan(MIC_KEY + r"\NonPackaged")
    return found


def own_names() -> set[str]:
    """Il nostro processo usa il microfono mentre registra: va escluso."""
    exe = os.path.basename(sys.executable).lower()
    return {exe, "python.exe", "pythonw.exe", "aitree.exe"}


def active_call_app(call_apps: list[str]) -> str | None:
    mine = own_names()
    for app in apps_using_mic():
        if app in mine:
            continue
        if any(k in app for k in call_apps):
            return app
    return None


def main_window_of(app_name: str) -> str | None:
    """Titolo della finestra visibile più grande del processo indicato."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    import psutil

    stem = app_name.lower().replace(".exe", "").split("_")[0]
    pids = {p.pid for p in psutil.process_iter(["name"])
            if p.info["name"] and stem in p.info["name"].lower()}
    user32 = ctypes.windll.user32
    best: tuple[int, str] | None = None

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        nonlocal best
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        area = (r.right - r.left) * (r.bottom - r.top)
        if best is None or area > best[0]:
            best = (area, buf.value)
        return True

    user32.EnumWindows(cb, 0)
    return best[1] if best else None


def pretty_app(app: str | None) -> str:
    if not app:
        return "Call"
    a = app.lower()
    for key, label in (("zoom", "Zoom"), ("teams", "Teams"), ("webex", "Webex"), ("slack", "Slack"),
                       ("chrome", "Browser"), ("msedge", "Browser"), ("edgemac", "Browser"), ("safari", "Browser"), ("firefox", "Browser"),
                       ("brave", "Browser"), ("whatsapp", "WhatsApp"), ("discord", "Discord")):
        if key in a:
            return label
    return app.replace(".exe", "")
