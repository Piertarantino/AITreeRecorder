"""Unione delle due tracce in una trascrizione Io/Loro, senza IA.

Filtro eco: se usi le casse, il microfono ricapta la voce degli altri e Whisper
la trascrive due volte. Un pezzo del microfono viene scartato quando si
sovrappone nel tempo a un pezzo dell'audio di sistema con testo molto simile.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from .transcribe import Segment

ECHO_SIMILARITY = 0.6


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _overlap(a: Segment, b: Segment) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def is_echo(mic: Segment, system: list[Segment]) -> bool:
    mw = _words(mic.text)
    if not mw:
        return True
    near = [s for s in system if _overlap(mic, s) > 0 or abs(s.start - mic.start) < 1.5]
    if not near:
        return False
    sw = [w for s in near for w in _words(s.text)]
    # Quanta parte del testo del microfono si ritrova nel testo di sistema.
    m = SequenceMatcher(None, mw, sw, autojunk=False)
    matched = sum(block.size for block in m.get_matching_blocks())
    return matched / len(mw) >= ECHO_SIMILARITY


def merge(mic: list[Segment], system: list[Segment]) -> tuple[list[Segment], int]:
    kept = [s for s in mic if not is_echo(s, system)]
    dropped = len(mic) - len(kept)
    allsegs = sorted(kept + system, key=lambda s: (s.start, s.end))
    # Unisce frasi consecutive dello stesso interlocutore vicine nel tempo.
    out: list[Segment] = []
    for s in allsegs:
        if out and out[-1].speaker == s.speaker and s.start - out[-1].end < 1.5:
            last = out[-1]
            out[-1] = Segment(last.start, max(last.end, s.end), f"{last.text} {s.text}", last.speaker)
        else:
            out.append(Segment(s.start, s.end, s.text, s.speaker))
    return out, dropped


def _ts(sec: float, srt: bool = False) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    if srt:
        return f"{h:02}:{m:02}:{s:02},{int((sec % 1) * 1000):03}"
    return f"{h:02}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"


def to_markdown(segs: list[Segment], title: str) -> str:
    lines = [f"# {title}", ""]
    for s in segs:
        lines.append(f"**[{_ts(s.start)}] {s.speaker}:** {s.text}")
        lines.append("")
    return "\n".join(lines)


def to_srt(segs: list[Segment]) -> str:
    blocks = []
    for i, s in enumerate(segs, 1):
        blocks.append(f"{i}\n{_ts(s.start, True)} --> {_ts(s.end, True)}\n{s.speaker}: {s.text}\n")
    return "\n".join(blocks)


def to_json(segs: list[Segment]) -> str:
    return json.dumps(
        [{"start": round(s.start, 2), "end": round(s.end, 2), "speaker": s.speaker, "text": s.text} for s in segs],
        ensure_ascii=False, indent=2,
    )
