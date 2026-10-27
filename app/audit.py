"""Journal d'audit immuable.

Toute manipulation de compte, session, événement ou accès sensible est
consignée dans core.audit_log. La table est protégée par un trigger qui
interdit UPDATE/DELETE/TRUNCATE (voir sql/core.sql).
"""

import json
from flask import request, has_request_context

from .db import core_conn


def client_ip() -> str | None:
    """IP client réelle (X-Forwarded-For seulement si TRUST_PROXY)."""
    if not has_request_context():
        return None
    from flask import current_app

    if current_app.config.get("TRUST_PROXY"):
        fwd = request.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.remote_addr


def log(action: str, *, actor_role: str = "system", actor_id=None,
        actor_label: str = "", session_id=None, target_type: str = None,
        target_id=None, details: dict | None = None, conn=None) -> None:
    """Insère une entrée dans le journal d'audit.

    `conn` optionnel : pour inclure le log dans la transaction de l'appelant
    (atomicité action + audit).
    """
    ip = client_ip()
    payload = (
        session_id and str(session_id),
        actor_role,
        actor_id and str(actor_id),
        actor_label or "",
        action,
        target_type,
        target_id and str(target_id),
        json.dumps(details or {}),
        ip,
    )
    sql = (
        "INSERT INTO core.audit_log "
        "(session_id, actor_role, actor_id, actor_label, action, "
        " target_type, target_id, details, ip) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)"
    )
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(sql, payload)
    else:
        with core_conn() as c:
            with c.cursor() as cur:
                cur.execute(sql, payload)


def list_logs(session_id=None, limit: int = 200) -> list[dict]:
    """Lecture seule du journal (admin session ou superadmin)."""
    with core_conn() as conn:
        with conn.cursor() as cur:
            if session_id:
                cur.execute(
                    "SELECT * FROM core.audit_log WHERE session_id = %s "
                    "ORDER BY ts DESC LIMIT %s",
                    (str(session_id), limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM core.audit_log ORDER BY ts DESC LIMIT %s",
                    (limit,),
                )
            return [dict(r) for r in cur.fetchall()]
