"""Invio facoltativo del report per email (SMTP, es. Gmail con password per le app)."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path

from .config import EmailSettings


def send_report(es: EmailSettings, subject: str, body_md: str, attachments: list[Path]) -> None:
    if not (es.enabled and es.smtp_host and es.to):
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = es.sender or es.username
    msg["To"] = ", ".join(es.to)
    msg.set_content(body_md)
    for p in attachments:
        if p.exists() and p.stat().st_size < 15_000_000:
            msg.add_attachment(p.read_bytes(), maintype="text", subtype="markdown", filename=p.name)
    with smtplib.SMTP(es.smtp_host, es.smtp_port, timeout=30) as s:
        s.starttls()
        if es.username:
            s.login(es.username, es.password)
        s.send_message(msg)
