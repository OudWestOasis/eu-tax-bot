# -*- coding: utf-8 -*-
"""
E-mail versturen via SMTP (standaard Gmail).

Inloggegevens komen uit environment-variabelen (GitHub Secrets):
  SMTP_USER  - je Gmail-adres (tevens afzender)
  SMTP_PASS  - een Gmail APP-WACHTWOORD (16 tekens, niet je gewone wachtwoord!)
optioneel:
  SMTP_HOST  - default smtp.gmail.com
  SMTP_PORT  - default 587 (STARTTLS)
"""

import os
import ssl
import smtplib
from email.message import EmailMessage


def send_email(to_addr, subject, html_body, text_body=None):
    user = os.environ.get("SMTP_USER", "").strip()
    pw = os.environ.get("SMTP_PASS", "").strip()
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))

    if not user or not pw:
        raise RuntimeError("SMTP_USER / SMTP_PASS ontbreken (zet ze als GitHub Secrets).")
    if not to_addr:
        raise RuntimeError("Geen ontvanger (EMAIL_TO / email_to) ingesteld.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(text_body or "Bekijk deze e-mail in HTML-weergave.")
    msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=context)
        server.login(user, pw)
        server.send_message(msg)
    return True
