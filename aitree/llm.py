"""Pacchetto per LLM e invio facoltativo a Claude, ChatGPT o Gemini.

1. pacchetto-llm.md   sempre creato: istruzioni + dati della call + trascrizione.
                      Si trascina o incolla in qualsiasi chat di IA.
2. Apertura chat      copia il pacchetto negli appunti e apre claude.ai,
                      chatgpt.com o gemini: basta Ctrl+V e Invio.
3. API                con una chiave API il riassunto arriva da solo in
                      riassunto-ia.md, senza aprire niente.

Nota: gli abbonamenti Claude Pro / ChatGPT Plus / Gemini Advanced non
includono l'accesso API e non esiste un modo ufficiale per creare
conversazioni nel loro sito da un programma; per l'automazione completa
serve una chiave API (a consumo, pochi centesimi a call).
"""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

DEFAULT_PROMPT = """\
Sei l'assistente che prepara il resoconto di una call di lavoro.
Qui sotto trovi i dati della call e la trascrizione automatica.

Scrivi in italiano (o nella lingua prevalente della call), in Markdown:
1. **Riassunto** in 5-10 righe.
2. **Decisioni prese.**
3. **Azioni da fare**: chi, cosa, entro quando (solo se detto).
4. **Punti aperti** e domande rimaste senza risposta.
5. **Posizioni dei partecipanti**: cosa ha sostenuto ciascuno.

Regole:
- La trascrizione è automatica e può contenere errori di parole o nomi:
  correggi solo quando il senso è evidente, altrimenti segnala il dubbio.
- "Io" (o il nome in "Chi ha registrato") è la persona che ha registrato. "Loro" sono tutti gli altri partecipanti
  insieme, salvo quando compaiono nomi distinti.
- Non inventare nulla che non sia nella trascrizione.
"""

CHAT_URLS = {
    "claude": "https://claude.ai/new",
    "chatgpt": "https://chatgpt.com/",
    "gemini": "https://gemini.google.com/app",
}
DEFAULT_MODELS = {"claude": "claude-opus-5-5"}


def build_pack(meta: dict, report_md: str, transcript_lines: list[str], prompt: str = "",
               me: str = "Io") -> str:
    parts = [
        "# Pacchetto call per IA", "",
        "## Istruzioni", "", (prompt or DEFAULT_PROMPT).strip(), "",
        "## Dati della call", "",
        f"- Titolo: {meta.get('title', 'Call')}",
        f"- App: {meta.get('app', '-')}",
        f"- Chi ha registrato: {me}",
        f"- Durata: {round(meta.get('duration_s', 0) / 60)} minuti",
        f"- Lingua di trascrizione: {meta.get('language', 'it')}", "",
        "## Statistiche (calcolate senza IA)", "",
        _strip_title(report_md), "",
        "## Trascrizione", "",
        "Formato: [minuti:secondi] Chi: testo", "",
        *transcript_lines, "",
    ]
    return "\n".join(parts)


def _strip_title(md: str) -> str:
    # Il report ha già titolo e rimando ai file: nel pacchetto tieni solo le sezioni utili.
    lines = md.splitlines()
    out = [l.replace("## ", "### ") for l in lines[1:] if not l.startswith("Trascrizione completa")]
    while out and out[-1] in ("", "---"):
        out.pop()
    return "\n".join(out).strip()


# ── Apertura chat nel browser ────────────────────────────────────────────────

def copy_to_clipboard(path: Path) -> bool:
    if sys.platform == "darwin":
        r = subprocess.run(["pbcopy"], input=path.read_bytes(), env={**os.environ, "LANG": "en_US.UTF-8"})
        return r.returncode == 0
    if sys.platform != "win32":
        return False
    cmd = ["powershell", "-NoProfile", "-Command",
           f"Get-Content -Raw -Encoding UTF8 -LiteralPath '{path}' | Set-Clipboard"]
    return subprocess.run(cmd, capture_output=True, creationflags=0x08000000).returncode == 0


def open_chat(service: str, pack: Path) -> str:
    url = CHAT_URLS.get(service)
    if not url:
        return f"Chat sconosciuta: {service}. Usa claude, chatgpt o gemini."
    copied = copy_to_clipboard(pack)
    webbrowser.open(url)
    if copied:
        return f"Pacchetto copiato negli appunti e {service} aperto: incolla con Ctrl+V e premi Invio."
    return f"{service} aperto: trascina nella chat il file {pack}."


# ── Invio via API ────────────────────────────────────────────────────────────

def _key(provider: str, configured: str) -> str:
    env = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}[provider]
    return configured or os.environ.get(env, "")


def send(provider: str, pack_text: str, api_key: str = "", model: str = "") -> str:
    """Invia il pacchetto e ritorna il testo della risposta."""
    provider = provider.lower()
    if provider not in ("claude", "openai", "gemini"):
        raise ValueError("Provider non valido: usa claude, openai o gemini.")
    key = _key(provider, api_key)
    model = model or DEFAULT_MODELS.get(provider, "")
    if not model:
        raise ValueError(f"Per {provider} indica il modello in config.json (llm.model).")

    if provider == "claude":
        import anthropic  # pip install anthropic

        client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        # Streaming: le trascrizioni lunghe possono richiedere qualche minuto.
        # fallbacks="default": se il modello declina, l'API riprova da sola su un altro modello.
        with client.beta.messages.stream(
            model=model,
            max_tokens=16000,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": pack_text}],
        ) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason == "refusal":
            raise RuntimeError("Claude ha declinato la richiesta.")
        return "".join(b.text for b in msg.content if b.type == "text")

    if provider == "openai":
        from openai import OpenAI  # pip install openai

        client = OpenAI(api_key=key) if key else OpenAI()
        return client.responses.create(model=model, input=pack_text).output_text

    from google import genai  # pip install google-genai

    client = genai.Client(api_key=key) if key else genai.Client()
    return client.models.generate_content(model=model, contents=pack_text).text
