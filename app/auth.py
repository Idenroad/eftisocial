"""Authentification : OTP courriel + jetons de session persistants.

Trois rôles :
  - superadmin : global, cookie `efti_sa` (path=/superadmin)
  - admin      : rattaché à UNE session, cookie `efti_admin` (path=/<slug>/admin)
  - user       : membre d'UNE session, cookie `efti_user` (path=/<slug>)

L'isolation entre résidences est double : le jeton porte session_id ET le
cookie est scopé par chemin. Un compte de /residence1 ne peut rien faire dans
/residence2 — le jeton est rejeté au niveau du décorateur ET la connexion DB
est confinée au schéma de la session.
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import current_app, g, has_app_context, redirect, request, url_for

from . import audit
from .db import core_conn, sess_conn

UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(UTC)


def _cfg(key: str, default=None):
    """Config : Flask app context si dispo, sinon env / défauts Config.

    Permet d'appeler les fonctions d'auth hors requête (tests, scripts).
    """
    if has_app_context():
        return current_app.config[key]
    from .config import Config
    return getattr(Config, key, os.environ.get(key, default))


def _hash(value: str) -> str:
    """Empreinte SHA-256 poivrée avec SECRET_KEY (codes OTP, jetons)."""
    return hashlib.sha256(f"{value}:{_cfg('SECRET_KEY')}".encode()).hexdigest()


# ─── OTP ──────────────────────────────────────────────────────────────────────

def request_otp(email: str, role: str, session_id, ip: str | None):
    """Crée un OTP (6 chiffres). Retourne (code, erreur).

    Le code en clair n'est retourné que pour l'envoi courriel — jamais stocké.
    """
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM core.otp_codes "
                "WHERE email = %s AND session_id IS NOT DISTINCT FROM %s "
                "AND created_at > now() - interval '1 hour'",
                (email, session_id),
            )
            if cur.fetchone()["n"] >= _cfg("OTP_REQUEST_LIMIT_PER_HOUR"):
                from .i18n import tr
                return None, tr("Trop de demandes. Réessayez plus tard.")

            # Invalide les anciens codes non utilisés
            cur.execute(
                "UPDATE core.otp_codes SET used = true "
                "WHERE email = %s AND session_id IS NOT DISTINCT FROM %s "
                "AND used = false",
                (email, session_id),
            )

            code = f"{secrets.randbelow(1000000):06d}"
            cur.execute(
                "INSERT INTO core.otp_codes "
                "(email, session_id, role, code_hash, expires_at, ip) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    email, session_id, role, _hash(code),
                    _now() + timedelta(seconds=_cfg("OTP_TTL_SECONDS")), ip,
                ),
            )
    return code, None


def _account_demo_otp(email: str, role: str, session) -> str | None:
    """OTP statique de démo du compte visé (None en production)."""
    if role == "superadmin":
        with core_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT demo_otp FROM core.superadmins "
                    "WHERE email = %s AND active = true", (email,))
                row = cur.fetchone()
        return row["demo_otp"] if row else None
    if role == "admin":
        with core_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT demo_otp FROM core.admins "
                    "WHERE email = %s AND session_id = %s AND active = true",
                    (email, session["id"]))
                row = cur.fetchone()
        return row["demo_otp"] if row else None
    # user
    with sess_conn(session["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT demo_otp FROM users "
                "WHERE email = %s AND deleted_at IS NULL", (email,))
            row = cur.fetchone()
    return row["demo_otp"] if row else None


def verify_otp(email: str, role: str, session, code: str) -> bool:
    """Vérifie un code OTP (ou le code statique de démo du compte)."""
    code = (code or "").strip()

    demo = _account_demo_otp(email, role, session)
    if demo and secrets.compare_digest(code, demo):
        return True

    session_id = session["id"] if session else None
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, code_hash, attempts FROM core.otp_codes "
                "WHERE email = %s AND session_id IS NOT DISTINCT FROM %s "
                "AND role = %s AND used = false AND expires_at > now() "
                "ORDER BY created_at DESC LIMIT 1",
                (email, session_id, role),
            )
            row = cur.fetchone()
            if not row or row["attempts"] >= _cfg("OTP_MAX_ATTEMPTS"):
                return False
            cur.execute(
                "UPDATE core.otp_codes SET attempts = attempts + 1 WHERE id = %s",
                (row["id"],),
            )
            if not secrets.compare_digest(_hash(code), row["code_hash"]):
                return False
            cur.execute(
                "UPDATE core.otp_codes SET used = true WHERE id = %s",
                (row["id"],),
            )
    return True


# ─── Jetons de session ────────────────────────────────────────────────────────

def issue_token(role: str, actor_id, session_id, remember: bool,
                ip: str | None, ua: str | None) -> str:
    """Crée un jeton en DB et retourne la valeur brute pour le cookie."""
    raw = secrets.token_urlsafe(32)
    ttl = (timedelta(days=_cfg("TOKEN_TTL_REMEMBER_DAYS")) if remember
           else timedelta(hours=_cfg("TOKEN_TTL_HOURS")))
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO core.auth_tokens "
                "(token_hash, role, session_id, actor_id, remember, "
                " expires_at, ip, ua) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (_hash(raw), role, session_id, str(actor_id), remember,
                 _now() + ttl, ip, (ua or "")[:300]),
            )
    return raw


def resolve_token(raw: str, role: str, session_id) -> dict | None:
    """Valide un jeton brut. Retourne la ligne token ou None."""
    if not raw:
        return None
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM core.auth_tokens "
                "WHERE token_hash = %s AND role = %s "
                "AND session_id IS NOT DISTINCT FROM %s "
                "AND revoked = false AND expires_at > now()",
                (_hash(raw), role, session_id),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def revoke_token(raw: str) -> None:
    if not raw:
        return
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE core.auth_tokens SET revoked = true WHERE token_hash = %s",
                (_hash(raw),),
            )


def revoke_actor_tokens(role: str, actor_id) -> None:
    """Révoque tous les jetons d'un compte (ex. suppression/pause forcée)."""
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE core.auth_tokens SET revoked = true "
                "WHERE role = %s AND actor_id = %s AND revoked = false",
                (role, str(actor_id)),
            )


# ─── Cookies ──────────────────────────────────────────────────────────────────

COOKIE_NAMES = {"superadmin": "efti_sa", "admin": "efti_admin", "user": "efti_user"}


def _cookie_path(role: str, slug: str | None) -> str:
    if role == "superadmin":
        return "/superadmin"
    if role == "admin":
        return f"/{slug}/admin"
    return f"/{slug}"


def set_auth_cookie(resp, role: str, slug: str | None, raw: str, remember: bool):
    """Pose le cookie de jeton (HttpOnly, SameSite=Lax, scopé par chemin)."""
    resp.set_cookie(
        COOKIE_NAMES[role], raw,
        max_age=(_cfg("TOKEN_TTL_REMEMBER_DAYS") * 86400) if remember else None,
        path=_cookie_path(role, slug),
        httponly=True, samesite="Lax",
        secure=_cfg("SESSION_COOKIE_SECURE"),
    )


def clear_auth_cookie(resp, role: str, slug: str | None):
    resp.delete_cookie(COOKIE_NAMES[role], path=_cookie_path(role, slug))


def read_cookie(role: str) -> str | None:
    return request.cookies.get(COOKIE_NAMES[role])


# ─── Décorateurs d'accès ──────────────────────────────────────────────────────

def _login_redirect(role: str, slug: str | None):
    if role == "superadmin":
        return redirect(url_for("superadmin.login"))
    if role == "admin":
        return redirect(url_for("session_admin.login", slug=slug))
    return redirect(url_for("user_app.login", slug=slug))


def require_superadmin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        tok = resolve_token(read_cookie("superadmin"), "superadmin", None)
        if not tok:
            return _login_redirect("superadmin", None)
        with core_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email, first_name FROM core.superadmins "
                    "WHERE id = %s AND active = true", (str(tok["actor_id"]),))
                actor = cur.fetchone()
        if not actor:
            return _login_redirect("superadmin", None)
        g.actor = dict(actor)
        g.role = "superadmin"
        g.token = tok["token_hash"]
        g.raw_token = read_cookie("superadmin")
        return f(*args, **kwargs)
    return wrapper


def require_admin(f):
    """Accès admin d'UNE session. Vérifie session + rattachement + actif."""
    @wraps(f)
    def wrapper(slug, *args, **kwargs):
        from .db import get_session_by_slug
        session = get_session_by_slug(slug)
        if not session or not session["active"]:
            return _login_redirect("admin", slug)
        tok = resolve_token(read_cookie("admin"), "admin", session["id"])
        if not tok:
            return _login_redirect("admin", slug)
        with core_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email, first_name FROM core.admins "
                    "WHERE id = %s AND session_id = %s AND active = true",
                    (str(tok["actor_id"]), session["id"]))
                actor = cur.fetchone()
        if not actor:
            return _login_redirect("admin", slug)
        g.actor = dict(actor)
        g.role = "admin"
        g.session = session
        g.raw_token = read_cookie("admin")
        return f(slug, *args, **kwargs)
    return wrapper


def require_user(f):
    """Accès membre d'UNE session. Jeton scopé + compte non supprimé."""
    @wraps(f)
    def wrapper(slug, *args, **kwargs):
        from .db import get_session_by_slug
        session = get_session_by_slug(slug)
        if not session or not session["active"]:
            return _login_redirect("user", slug)
        tok = resolve_token(read_cookie("user"), "user", session["id"])
        if not tok:
            return _login_redirect("user", slug)
        with sess_conn(session["schema_name"]) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email, first_name, sex, paused FROM users "
                    "WHERE id = %s AND deleted_at IS NULL",
                    (str(tok["actor_id"]),))
                actor = cur.fetchone()
        if not actor:
            return _login_redirect("user", slug)
        g.actor = dict(actor)
        g.role = "user"
        g.session = session
        g.raw_token = read_cookie("user")
        return f(slug, *args, **kwargs)
    return wrapper
