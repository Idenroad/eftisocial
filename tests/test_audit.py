"""Tests du journal d'audit immuable."""

import pytest
import psycopg

from .conftest import (login_user, mk_admin, mk_session, mk_user, post)


def _log_rows(app, session_id=None):
    conn = psycopg.connect(app.config["DATABASE_URL"], autocommit=True)
    try:
        with conn.cursor() as cur:
            if session_id:
                cur.execute(
                    "SELECT action FROM core.audit_log "
                    "WHERE session_id = %s ORDER BY id", (str(session_id),))
            else:
                cur.execute(
                    "SELECT action FROM core.audit_log ORDER BY id")
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def test_audit_immutable(app):
    """UPDATE et DELETE sur audit_log lèvent une erreur (trigger)."""
    from app import audit
    with app.app_context():
        audit.log("test.entry", actor_role="system")
    conn = psycopg.connect(app.config["DATABASE_URL"], autocommit=True)
    try:
        with conn.cursor() as cur:
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("UPDATE core.audit_log SET action='x'")
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("DELETE FROM core.audit_log")
            with pytest.raises(psycopg.errors.RaiseException):
                cur.execute("TRUNCATE core.audit_log")
    finally:
        conn.close()
    # La ligne existe toujours
    assert "test.entry" in _log_rows(app)


def test_actions_are_logged(app, client):
    """Création de compte par admin + login usager + match : tout est tracé."""
    s = mk_session("res-au-a")
    mk_admin(s["id"], "int@a.local", otp="4444")
    mk_user(s["schema_name"], "u@a.local", otp="111111")

    with app.test_client() as c1:
        c1.post("/res-au-a/admin/connexion",
                data={"email": "int@a.local", "csrf_token": _csrf(c1, "/res-au-a/admin/connexion")})
        c1.post("/res-au-a/admin/connexion/verification",
                data={"code": "4444",
                      "csrf_token": _csrf(c1, "/res-au-a/admin/connexion/verification")})
        c1.post("/res-au-a/admin/utilisateurs",
                data={"csrf_token": _csrf(c1, "/res-au-a/admin/utilisateurs"),
                      "first_name": "Rita", "email": "rita@a.local",
                      "sex": "F"})

    login_user(client, "res-au-a", "u@a.local", "111111")

    actions = _log_rows(app, s["id"])
    assert "auth.login" in actions
    assert "admin.user_create" in actions


def test_audit_survives_session_delete(app, client):
    """Le log survit à la suppression de la session (SET NULL)."""
    from .conftest import login_superadmin, mk_superadmin
    s = mk_session("res-au-b")
    mk_superadmin("sa@a.local", otp="999999")
    login_superadmin(client, "sa@a.local", "999999")
    from .conftest import csrf_of
    tok = csrf_of(client, "/superadmin/sessions")
    resp = client.post(f"/superadmin/sessions/res-au-b/supprimer",
                       data={"csrf_token": tok, "confirm": "res-au-b"})
    assert resp.status_code == 302
    rows = _log_rows(app)
    assert "session.delete" in rows


def _csrf(client, url):
    import re
    resp = client.get(url)
    m = re.search(r'name="csrf-token" content="([^"]+)"',
                  resp.get_data(as_text=True))
    return m.group(1) if m else ""
