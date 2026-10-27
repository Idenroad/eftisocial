"""Tests du moteur de swipe : pile, classement par intérêts, match, pause."""

import pytest

from app import matching
from .conftest import csrf_of, login_user, mk_session, mk_user


def _swipe(client, slug, target, action):
    tok = csrf_of(client, f"/{slug}/trouver")
    return client.post(
        f"/{slug}/api/swipe", json={"target": target, "action": action},
        headers={"X-CSRFToken": tok})


def test_deck_ordered_by_shared_interests(app, client):
    s = mk_session("res-sw-a")
    me = mk_user(s["schema_name"], "me@t.local", otp="111111",
                 interests=["marche", "jardinage", "bingo"])
    u1 = mk_user(s["schema_name"], "u1@t.local", interests=["marche"])
    u2 = mk_user(s["schema_name"], "u2@t.local",
                 interests=["marche", "jardinage", "bingo"])
    u3 = mk_user(s["schema_name"], "u3@t.local",
                 interests=["marche", "jardinage"])

    login_user(client, "res-sw-a", "me@t.local", "111111")
    resp = client.get("/res-sw-a/api/deck")
    cards = resp.get_json()["cards"]
    ids = [c["id"] for c in cards]
    assert ids.index(u2) < ids.index(u3) < ids.index(u1)
    assert cards[0]["shared"] == 3


def test_swipe_like_then_match(app, client):
    s = mk_session("res-sw-b")
    a = mk_user(s["schema_name"], "a@t.local", otp="111111",
                interests=["marche"])
    b = mk_user(s["schema_name"], "b@t.local", otp="222222",
                interests=["marche"])

    login_user(client, "res-sw-b", "a@t.local", "111111")
    r = _swipe(client, "res-sw-b", b, "like").get_json()
    assert r["ok"] and not r["matched"]

    # B se connecte (nouveau client = nouveau jar de cookies)
    c2 = app.test_client()
    login_user(c2, "res-sw-b", "b@t.local", "222222")
    r = _swipe(c2, "res-sw-b", a, "like").get_json()
    assert r["matched"] and r["match_id"]

    matches = matching.list_matches(s["schema_name"], a)
    assert len(matches) == 1 and str(matches[0]["id"]) == b


def test_pass_excludes_from_deck(app, client):
    s = mk_session("res-sw-c")
    me = mk_user(s["schema_name"], "me@c.local", otp="111111")
    other = mk_user(s["schema_name"], "o@c.local")
    login_user(client, "res-sw-c", "me@c.local", "111111")
    r = _swipe(client, "res-sw-c", other, "pass").get_json()
    assert r["ok"]
    cards = client.get("/res-sw-c/api/deck").get_json()["cards"]
    assert all(c["id"] != other for c in cards)


def test_paused_user_hidden(app, client):
    s = mk_session("res-sw-d")
    me = mk_user(s["schema_name"], "me@d.local", otp="111111")
    other = mk_user(s["schema_name"], "o@d.local")
    from app.db import sess_conn
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET paused=true WHERE id=%s", (other,))
    login_user(client, "res-sw-d", "me@d.local", "111111")
    cards = client.get("/res-sw-d/api/deck").get_json()["cards"]
    assert all(c["id"] != other for c in cards)


def test_cannot_swipe_paused_target(app, client):
    """Même en forçant l'API, on ne peut pas liker un compte en pause."""
    s = mk_session("res-sw-e")
    me = mk_user(s["schema_name"], "me@e.local", otp="111111")
    other = mk_user(s["schema_name"], "o@e.local")
    from app.db import sess_conn
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET paused=true WHERE id=%s", (other,))
    login_user(client, "res-sw-e", "me@e.local", "111111")
    r = _swipe(client, "res-sw-e", other, "like").get_json()
    assert r["ok"] and not r["matched"]
    # Et le swipe n'est même pas enregistré
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM swipes")
            assert cur.fetchone()["n"] == 0


def test_swipe_invalid_params(app, client):
    s = mk_session("res-sw-f")
    mk_user(s["schema_name"], "me@f.local", otp="111111")
    login_user(client, "res-sw-f", "me@f.local", "111111")
    r = _swipe(client, "res-sw-f", "pas-un-uuid", "like")
    assert r.status_code == 400
    r = _swipe(client, "res-sw-f",
               "00000000-0000-0000-0000-000000000000", "boom")
    assert r.status_code == 400
