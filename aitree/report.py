"""Report della call senza IA: chi ha parlato quanto, parole chiave, momenti.

Tutto calcolato dalla trascrizione con semplici conteggi.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

from .transcribe import Segment

STOPWORDS = set("""
a ad al alla alle allo ai agli all anche ancora avere abbiamo avete hanno ha ho hai
c che chi ci cioè come con cosa così cui da dal dalla dalle dai dagli del della delle dello dei degli
di dove dunque e è ed era erano essere fa fare fatto forse fra gli ha i il in io la le lei li lo loro
lui ma me mi mia mie miei mio molto ne nei nel nella nelle nello no noi non nostro o oppure
per perché però più poi può qua qual quale quando quanto quello questa queste questi questo qui
se sei si sia siamo siete solo sono su sua sue sui sul sulla suo suoi sì ti tra tu tua tuo tutti tutto
un una uno vi voi vostro allora ok okay va bene sì beh ecco cioè tipo proprio quindi comunque
adesso ora già sempre mai dire detto vedere sto sta stai stiamo devo deve dobbiamo posso possiamo
vuoi voglio volevo c'è ce sarà sarebbe stato stata ehm eh mh uhm
the a an and or but of to in on at for with is are was were be been it this that you we they i
he she so not do does did have has had will would can could just yeah yes no ok okay like
""".split())


def _fmt_dur(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02}m" if h else f"{m}m {s:02}s"


def stats(segs: list[Segment], duration: float) -> dict:
    talk: dict[str, float] = {}
    words: dict[str, int] = {}
    turns: Counter = Counter()
    longest = None
    for s in segs:
        d = max(0.0, s.end - s.start)
        talk[s.speaker] = talk.get(s.speaker, 0.0) + d
        words[s.speaker] = words.get(s.speaker, 0) + len(s.text.split())
        turns[s.speaker] += 1
        if longest is None or d > longest.end - longest.start:
            longest = s
    total_talk = sum(talk.values()) or 1.0
    return {
        "duration": duration,
        "speakers": [
            {"name": n, "seconds": talk[n], "share": talk[n] / total_talk,
             "words": words[n], "turns": turns[n]}
            for n in sorted(talk, key=talk.get, reverse=True)
        ],
        "silence_share": max(0.0, 1 - total_talk / duration) if duration else 0.0,
        "longest": longest,
    }


def keywords(segs: list[Segment], n: int = 12) -> list[tuple[str, int]]:
    c: Counter = Counter()
    for s in segs:
        for w in re.findall(r"[a-zàèéìòù][a-zàèéìòù'0-9]{3,}", s.text.lower()):
            if w not in STOPWORDS:
                c[w] += 1
    return [(w, k) for w, k in c.most_common(n) if k > 1]


def questions(segs: list[Segment], n: int = 15) -> list[Segment]:
    return [s for s in segs if s.text.rstrip().endswith("?")][:n]


def build_report(meta: dict, segs: list[Segment]) -> str:
    st = stats(segs, meta.get("duration_s", 0))
    started = datetime.fromtimestamp(meta["started_at"]).strftime("%d/%m/%Y %H:%M") if meta.get("started_at") else ""
    lines = [f"# {meta.get('title', 'Call')}", "",
             f"- **Data:** {started}",
             f"- **Durata:** {_fmt_dur(st['duration'])}",
             f"- **App:** {meta.get('app', '-')}",
             f"- **Silenzio:** {st['silence_share']:.0%} del tempo", "",
             "## Chi ha parlato quanto", "",
             "| Chi | Tempo | Quota | Interventi | Parole |", "|---|---|---|---|---|"]
    for sp in st["speakers"]:
        bar = "█" * round(sp["share"] * 20)
        lines.append(f"| {sp['name']} | {_fmt_dur(sp['seconds'])} | {bar} {sp['share']:.0%} | {sp['turns']} | {sp['words']} |")
    kw = keywords(segs)
    if kw:
        lines += ["", "## Parole più ricorrenti", "", ", ".join(f"{w} ({k})" for w, k in kw)]
    q = questions(segs)
    if q:
        lines += ["", "## Domande fatte", ""]
        lines += [f"- [{_ts(s.start)}] **{s.speaker}:** {s.text}" for s in q]
    if st["longest"]:
        s = st["longest"]
        lines += ["", "## Intervento più lungo", "",
                  f"[{_ts(s.start)}] **{s.speaker}** ({_fmt_dur(s.end - s.start)}): {s.text[:400]}"
                  + ("…" if len(s.text) > 400 else "")]
    lines += ["", "---", "Trascrizione completa: `trascrizione.md`. "
              "Per un riassunto con un'IA usa `pacchetto-llm.md`.", ""]
    return "\n".join(lines)


def _ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"
