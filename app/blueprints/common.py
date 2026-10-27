"""Helpers partagés par les blueprints (flux OTP, validation)."""

import re

from flask import abort, session as flask_session

from .. import audit, auth, mailer
from ..db import core_conn, get_session_by_slug, sess_conn
from ..i18n import tr

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match((email or "").strip()))


def load_session_or_404(slug: str) -> dict:
    """Session par slug : 404 si inexistante, 403 si désactivée."""
    s = get_session_by_slug(slug)
    if not s:
        abort(404)
    if not s["active"]:
        abort(403)
    return s


def account_exists(email: str, role: str, session) -> bool:
    """Le courriel correspond-il à un compte du rôle demandé ?"""
    if role == "superadmin":
        with core_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM core.superadmins "
                    "WHERE email = %s AND active = true", (email,))
                return cur.fetchone() is not None
    if role == "admin":
        with core_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM core.admins "
                    "WHERE email = %s AND session_id = %s AND active = true",
                    (email, session["id"]))
                return cur.fetchone() is not None
    with sess_conn(session["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM users WHERE email = %s AND deleted_at IS NULL",
                (email,))
            return cur.fetchone() is not None


def start_otp(email: str, role: str, session, slug: str | None = None):
    """Crée un OTP si le compte existe et prépare le flux de vérification.

    Retourne (erreur, None). Message volontairement générique pour ne pas
    révéler si le courriel existe (anti-énumération).
    """
    email = (email or "").strip()
    if not valid_email(email):
        return tr("Adresse courriel invalide."), None

    if account_exists(email, role, session):
        code, err = auth.request_otp(
            email, role, session["id"] if session else None, audit.client_ip())
        if err:
            return err, None
        ctx = f"résidence {session['name']}" if session else "superadmin"
        mailer.send_otp(email, code, ctx)
        audit.log(
            "auth.otp_request", actor_role=role,
            actor_label=email,
            session_id=session["id"] if session else None,
            details={"context": ctx})

    # État du flux conservé dans la session Flask signée (pas dans l'URL)
    flask_session["pending"] = {
        "email": email, "role": role, "slug": slug,
        "session_id": str(session["id"]) if session else None,
    }
    return None, None


def complete_otp(email: str, role: str, session, code: str,
                 remember: bool) -> tuple:
    """Vérifie le code. Retourne (token_brut, actor_id) ou (None, erreur)."""
    email = (email or "").strip()
    if not auth.verify_otp(email, role, session, code):
        audit.log(
            "auth.otp_fail", actor_role=role, actor_label=email,
            session_id=session["id"] if session else None)
        return None, tr("Code invalide ou expiré.")

    # Résoudre l'acteur
    if role == "superadmin":
        with core_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM core.superadmins "
                    "WHERE email = %s AND active = true", (email,))
                row = cur.fetchone()
    elif role == "admin":
        with core_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM core.admins "
                    "WHERE email = %s AND session_id = %s AND active = true",
                    (email, session["id"]))
                row = cur.fetchone()
    else:
        with sess_conn(session["schema_name"]) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM users "
                    "WHERE email = %s AND deleted_at IS NULL", (email,))
                row = cur.fetchone()
    if not row:
        return None, tr("Compte introuvable.")

    raw = auth.issue_token(
        role, row["id"], session["id"] if session else None, remember,
        audit.client_ip(), request_ua())
    audit.log(
        "auth.login", actor_role=role, actor_id=row["id"],
        actor_label=email,
        session_id=session["id"] if session else None,
        details={"remember": remember})
    flask_session.pop("pending", None)
    return raw, row["id"]


def request_ua() -> str:
    from flask import request
    return request.headers.get("User-Agent", "")
