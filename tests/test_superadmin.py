"""Tests des pouvoirs du superadmin : sessions, intervenants, événements."""

from .conftest import (csrf_of, login_admin, login_superadmin, mk_admin,
                       mk_session, mk_superadmin, post)


def test_superadmin_creates_session(app, client):
    mk_superadmin("sa@t.local", otp="999999")
    login_superadmin(client, "sa@t.local", "999999")
    resp = post(client, "/superadmin/sessions", "/superadmin/sessions",
                data={"name": "Résidence Les Érables"})
    assert resp.status_code == 200
    from app.db import get_session_by_slug
    s = get_session_by_slug("residence-les-erables")
    assert s is not None and s["schema_name"] == "sess_residence_les_erables"
    # Le schéma et les répertoires existent
    import psycopg
    conn = psycopg.connect(app.config["DATABASE_URL"], autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM sess_residence_les_erables.users")
            assert cur.fetchone()[0] == 0
    finally:
        conn.close()
    from pathlib import Path
    assert (Path(app.config["DATA_DIR"]) / "residence-les-erables"
            / "profils").is_dir()


def test_superadmin_manages_admins(app, client):
    s = mk_session("res-sa-a")
    mk_superadmin("sa@a.local", otp="999999")
    login_superadmin(client, "sa@a.local", "999999")
    resp = post(client, "/superadmin/sessions/res-sa-a/admins",
                "/superadmin/sessions/res-sa-a/admins",
                data={"first_name": "Intervenant", "email": "int@a.local"})
    assert resp.status_code == 200
    # L'intervenant créé peut se connecter
    from app.db import core_conn
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE core.admins SET demo_otp='4444' "
                        "WHERE email='int@a.local'")
    login_admin(client, "res-sa-a", "int@a.local", "4444")
    assert client.get("/res-sa-a/admin/").status_code == 200


def test_session_toggle_blocks_access(app, client):
    s = mk_session("res-sa-b")
    mk_superadmin("sa@b.local", otp="999999")
    login_superadmin(client, "sa@b.local", "999999")
    post(client, "/superadmin/sessions/res-sa-b/basculer",
         "/superadmin/sessions")
    assert client.get("/res-sa-b/trouver").status_code == 302
    assert client.get("/res-sa-b/connexion").status_code == 403


def test_only_superadmin_reaches_superadmin(app, client):
    assert client.get("/superadmin/").status_code == 302
    # Un usager ou admin ne passe pas
    s = mk_session("res-sa-c")
    mk_admin(s["id"], "int@c.local", otp="4444")
    login_admin(client, "res-sa-c", "int@c.local", "4444")
    assert client.get("/superadmin/").status_code == 302


def test_superadmin_creates_event_in_session(app, client):
    s = mk_session("res-sa-d")
    mk_superadmin("sa@d.local", otp="999999")
    login_superadmin(client, "sa@d.local", "999999")
    from datetime import datetime, timedelta
    when = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    resp = post(client, "/superadmin/sessions/res-sa-d/evenements",
                "/superadmin/sessions/res-sa-d/evenements",
                data={"title": "Fête du printemps", "event_at": when})
    assert resp.status_code == 302
    from app.db import sess_conn
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title, creator_role FROM events")
            row = cur.fetchone()
    assert row["title"] == "Fête du printemps"
    assert row["creator_role"] == "superadmin"
