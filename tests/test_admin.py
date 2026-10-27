"""Tests des pouvoirs de l'intervenant (admin de session)."""

from .conftest import (csrf_of, login_admin, login_user, mk_admin, mk_session,
                       mk_user, post)


def test_admin_creates_user(app, client):
    s = mk_session("res-adm-a")
    mk_admin(s["id"], "int@a.local", otp="4444")
    login_admin(client, "res-adm-a", "int@a.local", "4444")
    resp = post(client, "/res-adm-a/admin/utilisateurs",
                "/res-adm-a/admin/utilisateurs",
                data={"first_name": "Ginette", "email": "ginette@x.local",
                      "sex": "F"})
    assert resp.status_code == 200
    from app.db import sess_conn
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT first_name, created_by FROM users "
                        "WHERE email='ginette@x.local'")
            row = cur.fetchone()
    assert row["first_name"] == "Ginette" and row["created_by"] == "admin"


def test_admin_duplicate_email_rejected(app, client):
    s = mk_session("res-adm-b")
    mk_admin(s["id"], "int@b.local", otp="4444")
    mk_user(s["schema_name"], "dup@b.local")
    login_admin(client, "res-adm-b", "int@b.local", "4444")
    resp = post(client, "/res-adm-b/admin/utilisateurs",
                "/res-adm-b/admin/utilisateurs",
                data={"first_name": "X", "email": "dup@b.local", "sex": "M"})
    assert "déjà utilisé" in resp.get_data(as_text=True)


def test_admin_edits_user(app, client):
    s = mk_session("res-adm-c")
    mk_admin(s["id"], "int@c.local", otp="4444")
    uid = mk_user(s["schema_name"], "u@c.local", first_name="Ancien")
    login_admin(client, "res-adm-c", "int@c.local", "4444")
    resp = post(client, f"/res-adm-c/admin/utilisateurs/{uid}",
                f"/res-adm-c/admin/utilisateurs/{uid}",
                data={"first_name": "Nouveau", "sex": "M",
                      "interests": ["marche", "bingo"], "paused": "on"})
    assert resp.status_code == 200
    from app.db import sess_conn
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT first_name, paused FROM users WHERE id=%s",
                        (uid,))
            row = cur.fetchone()
            cur.execute("SELECT interest FROM user_interests WHERE user_id=%s "
                        "ORDER BY interest", (uid,))
            ints = [r["interest"] for r in cur.fetchall()]
    assert row["first_name"] == "Nouveau" and row["paused"] is True
    assert ints == ["bingo", "marche"]


def test_admin_deletes_user(app, client):
    s = mk_session("res-adm-d")
    mk_admin(s["id"], "int@d.local", otp="4444")
    uid = mk_user(s["schema_name"], "u@d.local")
    login_admin(client, "res-adm-d", "int@d.local", "4444")
    resp = post(client, f"/res-adm-d/admin/utilisateurs/{uid}/supprimer",
                "/res-adm-d/admin/utilisateurs")
    assert resp.status_code == 302
    from app.db import sess_conn
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT deleted_at FROM users WHERE id=%s", (uid,))
            assert cur.fetchone()["deleted_at"] is not None


def test_deleted_user_cannot_login(app, client):
    s = mk_session("res-adm-e")
    mk_admin(s["id"], "int@e.local", otp="4444")
    uid = mk_user(s["schema_name"], "u@e.local", otp="111111")
    login_admin(client, "res-adm-e", "int@e.local", "4444")
    post(client, f"/res-adm-e/admin/utilisateurs/{uid}/supprimer",
         "/res-adm-e/admin/utilisateurs")
    # Le compte supprimé ne peut plus recevoir de code ni se connecter
    resp = login_user(client, "res-adm-e", "u@e.local", "111111")
    assert resp.status_code == 200
    assert b"invalide" in resp.data.lower()


def test_user_cannot_reach_admin_pages(app, client):
    """Un membre connecté n'accède pas au panneau intervenant."""
    s = mk_session("res-adm-f")
    mk_admin(s["id"], "int@f.local", otp="4444")
    mk_user(s["schema_name"], "u@f.local", otp="111111")
    login_user(client, "res-adm-f", "u@f.local", "111111")
    assert client.get("/res-adm-f/admin/").status_code == 302
    assert client.get("/res-adm-f/admin/utilisateurs").status_code == 302
    assert client.get("/res-adm-f/admin/journal").status_code == 302
