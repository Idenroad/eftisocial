"""Tests du flux d'authentification OTP (usager, admin, superadmin)."""

from .conftest import (login_admin, login_superadmin, login_user, mk_admin,
                       mk_session, mk_superadmin, mk_user, post)


def test_login_user_ok(app, client):
    s = mk_session("res-test-a")
    mk_user(s["schema_name"], "a@t.local", otp="111111")
    resp = login_user(client, "res-test-a", "a@t.local", "111111")
    assert resp.status_code == 302
    assert "/trouver" in resp.headers["Location"]
    # Le cookie est scopé au chemin de la session
    cookies = client.get_cookie("efti_user", path="/res-test-a")
    assert cookies is not None
    assert cookies.path == "/res-test-a"


def test_login_wrong_code(app, client):
    s = mk_session("res-test-b")
    mk_user(s["schema_name"], "b@t.local", otp="111111")
    resp = login_user(client, "res-test-b", "b@t.local", "000000")
    assert resp.status_code == 200  # reste sur la page avec erreur
    assert b"invalide" in resp.data.lower()


def test_login_unknown_email_no_otp(app, client):
    """Courriel inconnu : réponse identique (anti-énumération), pas de code."""
    s = mk_session("res-test-c")
    post(client, "/res-test-c/connexion", "/res-test-c/connexion",
         data={"email": "inconnu@t.local"})
    resp = post(client, "/res-test-c/connexion/verification",
                "/res-test-c/connexion/verification",
                data={"code": "111111"})
    assert b"invalide" in resp.data.lower()


def test_login_admin_ok(app, client):
    s = mk_session("res-test-d")
    mk_admin(s["id"], "int@t.local", otp="4444")
    resp = login_admin(client, "res-test-d", "int@t.local", "4444")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/admin/")


def test_login_superadmin_ok(app, client):
    mk_superadmin("sa@t.local", otp="999999")
    resp = login_superadmin(client, "sa@t.local", "999999")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/superadmin/")


def test_logout_revokes(app, client):
    s = mk_session("res-test-e")
    mk_user(s["schema_name"], "e@t.local", otp="111111")
    login_user(client, "res-test-e", "e@t.local", "111111")
    post(client, "/res-test-e/deconnexion", "/res-test-e/trouver")
    resp = client.get("/res-test-e/trouver")
    assert resp.status_code == 302  # redirigé vers connexion


def test_protected_redirects(app, client):
    s = mk_session("res-test-f")
    for url in ("/res-test-f/trouver", "/res-test-f/decouverte",
                "/res-test-f/evenements", "/res-test-f/mon-profil",
                "/res-test-f/api/deck", "/res-test-f/matchs"):
        resp = client.get(url)
        assert resp.status_code == 302, url
        assert "/connexion" in resp.headers["Location"]


def test_inactive_session_blocks(app, client):
    """Session désactivée : tout est fermé, même avec un jeton valide."""
    from app.db import core_conn
    s = mk_session("res-test-g")
    uid = mk_user(s["schema_name"], "g@t.local", otp="111111")
    login_user(client, "res-test-g", "g@t.local", "111111")
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE core.sessions SET active=false WHERE id=%s",
                        (s["id"],))
    resp = client.get("/res-test-g/trouver")
    assert resp.status_code == 302
