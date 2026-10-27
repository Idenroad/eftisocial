"""Envoi des codes OTP par courriel (SMTP stdlib).

En DEMO_MODE ou sans serveur SMTP configuré, le code est journalisé dans les
logs applicatifs au lieu d'être envoyé — utile en développement.
"""

import logging
import smtplib
from email.message import EmailMessage

from flask import current_app

log = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return bool(current_app.config.get("MAIL_SERVER"))


def send_email(to: str, subject: str, body: str) -> bool:
    """Envoie un courriel texte. Retourne True si envoyé, False sinon."""
    cfg = current_app.config
    if not cfg.get("MAIL_SERVER"):
        log.warning("SMTP non configuré — courriel pour %s non envoyé.", to)
        return False

    msg = EmailMessage()
    msg["From"] = cfg["MAIL_DEFAULT_SENDER"] or cfg["MAIL_USERNAME"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body, charset="utf-8")

    try:
        if cfg.get("MAIL_USE_SSL"):
            smtp = smtplib.SMTP_SSL(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15)
        else:
            smtp = smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15)
        with smtp:
            if cfg.get("MAIL_USE_TLS") and not cfg.get("MAIL_USE_SSL"):
                smtp.starttls()
            if cfg.get("MAIL_USERNAME"):
                smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            smtp.send_message(msg)
        return True
    except Exception:
        log.exception("Échec d'envoi du courriel à %s", to)
        return False


def _demo_mode() -> bool:
    import os
    from flask import has_app_context
    if has_app_context():
        return bool(current_app.config.get("DEMO_MODE"))
    return os.environ.get("DEMO_MODE", "").strip().lower() in (
        "1", "true", "yes", "o", "oui", "on")


def send_otp(to: str, code: str, context: str = "") -> bool:
    """Envoie le code de connexion. En démo, le code est écrit au log."""
    if _demo_mode():
        # Démo/dev : pas de SMTP requis — le code est affiché au log serveur
        print(f"[DEMO] OTP pour {to} ({context}): {code}", flush=True)
        return True
    subject = "Votre code de connexion EftiSocial"
    body = (
        f"Bonjour,\n\n"
        f"Votre code de connexion est : {code}\n\n"
        f"Il est valide 10 minutes.{(' ' + context) if context else ''}\n\n"
        f"Si vous n'avez pas demandé ce code, ignorez ce message.\n"
        f"— EftiSocial"
    )
    return send_email(to, subject, body)
