"""Tests du profil usager : édition, passions (max 10), pause, suppression,
pages Découverte et vue membre."""

from .conftest import csrf_of, login_user, mk_session, mk_user, post


def test_profile_update_and_interests(app, client):
    s = mk_session("res-pf-a")
    uid = mk_user(s["schema_name"], "u@a.local", otp="111111")
    login_user(client, "res-pf-a", "u@a.local", "111111")
    resp = post(client, "/res-pf-a/mon-profil", "/res-pf-a/mon-profil",
                data={"first_name": "Renée", "sex": "F", "bio": "J'aime lire",
                      "interests": "lecture, marche, bingo"})
    assert resp.status_code == 200
    from app import matching
    ints = matching.user_interests_for(s["schema_name"], uid)
    assert ints == ["bingo", "lecture", "marche"]


def test_interests_capped_at_10(app, client):
    s = mk_session("res-pf-b")
    uid = mk_user(s["schema_name"], "u@b.local", otp="111111")
    login_user(client, "res-pf-b", "u@b.local", "111111")
    post(client, "/res-pf-b/mon-profil", "/res-pf-b/mon-profil",
         data={"first_name": "X", "sex": "M",
               "interests": ", ".join(f"passion{i}" for i in range(15))})
    from app import matching
    ints = matching.user_interests_for(s["schema_name"], uid)
    assert len(ints) == 10


def test_pause_hides_and_unpause_restores(app, client):
    s = mk_session("res-pf-c")
    me = mk_user(s["schema_name"], "me@c.local", otp="111111")
    other = mk_user(s["schema_name"], "o@c.local", otp="222222")

    # other se met en pause
    c2 = app.test_client()
    login_user(c2, "res-pf-c", "o@c.local", "222222")
    post(c2, "/res-pf-c/mon-profil/pause", "/res-pf-c/mon-profil")

    # me ne voit plus other dans le deck ni en découverte
    login_user(client, "res-pf-c", "me@c.local", "111111")
    cards = client.get("/res-pf-c/api/deck").get_json()["cards"]
    assert all(c["id"] != other for c in cards)
    assert client.get(f"/res-pf-c/membre/{other}").status_code == 404

    # other se réactive → visible de nouveau
    post(c2, "/res-pf-c/mon-profil/pause", "/res-pf-c/mon-profil")
    cards = client.get("/res-pf-c/api/deck").get_json()["cards"]
    assert any(c["id"] == other for c in cards)


def test_discovery_pages(app, client):
    s = mk_session("res-pf-d")
    me = mk_user(s["schema_name"], "me@d.local", otp="111111",
                 interests=["marche", "jardinage"])
    other = mk_user(s["schema_name"], "o@d.local",
                    interests=["marche", "tricot"])
    login_user(client, "res-pf-d", "me@d.local", "111111")

    html = client.get("/res-pf-d/decouverte").get_data(as_text=True)
    assert "marche" in html and "tricot" in html

    html = client.get("/res-pf-d/decouverte/marche").get_data(as_text=True)
    assert "o@d" not in html  # pas de courriel affiché
    assert "O@d" not in html

    html = client.get(f"/res-pf-d/membre/{other}").get_data(as_text=True)
    assert "marche" in html


def test_delete_own_account(app, client):
    s = mk_session("res-pf-e")
    uid = mk_user(s["schema_name"], "u@e.local", otp="111111")
    login_user(client, "res-pf-e", "u@e.local", "111111")
    resp = post(client, "/res-pf-e/mon-profil/supprimer",
                "/res-pf-e/mon-profil", data={"confirm": "oui"})
    assert resp.status_code == 302
    # Compte supprimé : plus de login, token révoqué
    assert client.get("/res-pf-e/trouver").status_code == 302
    resp = login_user(client, "res-pf-e", "u@e.local", "111111")
    assert b"invalide" in resp.data.lower()


def test_delete_requires_confirm(app, client):
    s = mk_session("res-pf-f")
    uid = mk_user(s["schema_name"], "u@f.local", otp="111111")
    login_user(client, "res-pf-f", "u@f.local", "111111")
    post(client, "/res-pf-f/mon-profil/supprimer", "/res-pf-f/mon-profil")
    # Sans confirm=oui : compte toujours actif
    assert client.get("/res-pf-f/trouver").status_code == 200
