"""Tests du tchat : envoi, lecture, restriction aux deux membres du match."""

import uuid

from app import matching
from .conftest import csrf_of, login_user, mk_session, mk_user


def _match(schema, a, b):
    """Crée un match directement en DB (like réciproque simulé)."""
    matching.record_swipe(schema, a, b, "like")
    res = matching.record_swipe(schema, b, a, "like")
    assert res["matched"]
    return res["match_id"]


def _send(client, slug, mid, body):
    tok = csrf_of(client, f"/{slug}/matchs/{mid}")
    return client.post(
        f"/{slug}/matchs/{mid}/messages",
        json={"body": body}, headers={"X-CSRFToken": tok})


def _msgs(client, slug, mid, after=0):
    return client.get(f"/{slug}/matchs/{mid}/messages?after={after}")


def test_send_and_read_messages(app, client):
    s = mk_session("res-ch-a")
    a = mk_user(s["schema_name"], "a@t.local", otp="111111")
    b = mk_user(s["schema_name"], "b@t.local", otp="222222")
    mid = _match(s["schema_name"], a, b)

    login_user(client, "res-ch-a", "a@t.local", "111111")
    r = _send(client, "res-ch-a", mid, "Salut b !")
    assert r.status_code == 200
    assert r.get_json()["message"]["mine"] is True

    c2 = app.test_client()
    login_user(c2, "res-ch-a", "b@t.local", "222222")
    data = _msgs(c2, "res-ch-a", mid).get_json()
    assert len(data["messages"]) == 1
    assert data["messages"][0]["body"] == "Salut b !"
    assert data["messages"][0]["mine"] is False

    # Réponse de b → a la voit au poll suivant
    _send(c2, "res-ch-a", mid, "Salut a !")
    data = _msgs(client, "res-ch-a", mid, after=1).get_json()
    assert len(data["messages"]) == 1
    assert data["messages"][0]["mine"] is False  # envoyé par b, vu par a


def test_chat_page_marks_read(app, client):
    s = mk_session("res-ch-b")
    a = mk_user(s["schema_name"], "a@b.local", otp="111111")
    b = mk_user(s["schema_name"], "b@b.local", otp="222222")
    mid = _match(s["schema_name"], a, b)
    matching.send_message(s["schema_name"], mid, a, "allo")

    # b a 1 message non lu
    assert matching.unread_counts(s["schema_name"], b)[mid] == 1
    assert mid not in matching.unread_counts(s["schema_name"], a)

    c2 = app.test_client()
    login_user(c2, "res-ch-b", "b@b.local", "222222")
    assert c2.get(f"/res-ch-b/matchs/{mid}").status_code == 200
    assert mid not in matching.unread_counts(s["schema_name"], b)


def test_chat_restricted_to_match_members(app, client):
    """Un usager hors du match ne peut ni lire ni écrire."""
    s = mk_session("res-ch-c")
    a = mk_user(s["schema_name"], "a@c.local", otp="111111")
    b = mk_user(s["schema_name"], "b@c.local", otp="222222")
    z = mk_user(s["schema_name"], "z@c.local", otp="333333")
    mid = _match(s["schema_name"], a, b)

    login_user(client, "res-ch-c", "z@c.local", "333333")
    assert client.get(f"/res-ch-c/matchs/{mid}").status_code == 404
    assert _msgs(client, "res-ch-c", mid).status_code == 404
    assert _send(client, "res-ch-c", mid, "pirate").status_code == 404
    # Rien n'a été inséré
    assert matching.list_messages(s["schema_name"], mid, a) == []


def test_chat_cross_session(app, client):
    """Le match_id d'une session n'existe pas dans une autre."""
    sa = mk_session("res-ch-d")
    sb = mk_session("res-ch-e")
    a = mk_user(sa["schema_name"], "a@d.local", otp="111111")
    b = mk_user(sa["schema_name"], "b@d.local", otp="222222")
    mid = _match(sa["schema_name"], a, b)
    mk_user(sb["schema_name"], "z@e.local", otp="333333")

    login_user(client, "res-ch-e", "z@e.local", "333333")
    assert client.get(f"/res-ch-e/matchs/{mid}").status_code == 404


def test_empty_message_rejected(app, client):
    s = mk_session("res-ch-f")
    a = mk_user(s["schema_name"], "a@f.local", otp="111111")
    b = mk_user(s["schema_name"], "b@f.local", otp="222222")
    mid = _match(s["schema_name"], a, b)
    login_user(client, "res-ch-f", "a@f.local", "111111")
    assert _send(client, "res-ch-f", mid, "   ").status_code == 400
    assert _send(client, "res-ch-f", mid, "x" * 2001).status_code == 400
