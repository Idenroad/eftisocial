"""Tests : suppression de match (retour au pool), blocage, signalement,
catalogue de passions et interdictions."""

from app import matching
from .conftest import (csrf_of, login_admin, login_user, mk_admin, mk_session,
                       mk_user, post)


def _match(schema, a, b):
    matching.record_swipe(schema, a, b, "like")
    res = matching.record_swipe(schema, b, a, "like")
    assert res["matched"]
    return res["match_id"]


def test_unmatch_returns_to_pool(app, client):
    """Match supprimé : les deux profils réapparaissent dans le deck."""
    s = mk_session("res-mo-a")
    a = mk_user(s["schema_name"], "a@t.local", otp="111111")
    b = mk_user(s["schema_name"], "b@t.local", otp="222222")
    mid = _match(s["schema_name"], a, b)

    login_user(client, "res-mo-a", "a@t.local", "111111")
    post(client, f"/res-mo-a/matchs/{mid}/supprimer", "/res-mo-a/matchs")

    assert matching.list_matches(s["schema_name"], a) == []
    # b réapparaît dans le deck de a (swipes supprimés)
    cards = client.get("/res-mo-a/api/deck").get_json()["cards"]
    assert any(c["id"] == b for c in cards)


def test_block_hides_both_ways(app, client):
    """Blocage : invisibilité mutuelle (deck, découverte, profil, match)."""
    s = mk_session("res-mo-b")
    a = mk_user(s["schema_name"], "a@b.local", otp="111111",
                interests=["marche"])
    b = mk_user(s["schema_name"], "b@b.local", otp="222222",
                interests=["marche"])
    mid = _match(s["schema_name"], a, b)

    login_user(client, "res-mo-b", "a@b.local", "111111")
    post(client, f"/res-mo-b/membre/{b}/bloquer", "/res-mo-b/decouverte")

    # match détruit, decks vides des deux côtés
    assert matching.list_matches(s["schema_name"], a) == []
    cards_a = client.get("/res-mo-b/api/deck").get_json()["cards"]
    assert all(c["id"] != b for c in cards_a)
    assert client.get(f"/res-mo-b/membre/{b}").status_code == 404
    # b aussi ne voit plus a
    c2 = app.test_client()
    login_user(c2, "res-mo-b", "b@b.local", "222222")
    cards_b = c2.get("/res-mo-b/api/deck").get_json()["cards"]
    assert all(c["id"] != a for c in cards_b)
    # découverte : b absent de la liste "marche"
    members = matching.users_by_interest(s["schema_name"], a, "marche")
    assert all(m["id"] != uuid_or(b) for m in members)


def uuid_or(v):
    import uuid
    return str(v) if isinstance(v, uuid.UUID) else v


def test_unblock_restores(app, client):
    s = mk_session("res-mo-c")
    a = mk_user(s["schema_name"], "a@c.local", otp="111111")
    b = mk_user(s["schema_name"], "b@c.local", otp="222222")
    login_user(client, "res-mo-c", "a@c.local", "111111")
    post(client, f"/res-mo-c/membre/{b}/bloquer", "/res-mo-c/decouverte")
    post(client, f"/res-mo-c/membre/{b}/debloquer", "/res-mo-c/mon-profil")
    cards = client.get("/res-mo-c/api/deck").get_json()["cards"]
    assert any(c["id"] == b for c in cards)


def test_report_reaches_admin(app, client):
    s = mk_session("res-mo-d")
    mk_admin(s["id"], "int@d.local", otp="4444")
    a = mk_user(s["schema_name"], "a@d.local", otp="111111")
    b = mk_user(s["schema_name"], "b@d.local", otp="222222")
    login_user(client, "res-mo-d", "a@d.local", "111111")
    post(client, f"/res-mo-d/membre/{b}/signaler", "/res-mo-d/decouverte",
         data={"reason": "comportement", "details": "Message déplacé"})

    reports = matching.list_reports(s["schema_name"])
    assert len(reports) == 1 and reports[0]["reason"] == "comportement"
    rid = reports[0]["id"]

    # L'intervenant voit le signalement et le marque traité
    c2 = app.test_client()
    login_admin(c2, "res-mo-d", "int@d.local", "4444")
    html = c2.get("/res-mo-d/admin/signalements").get_data(as_text=True)
    assert "Message déplacé" in html
    post(c2, f"/res-mo-d/admin/signalements/{rid}/traite",
         "/res-mo-d/admin/signalements")
    assert matching.list_reports(s["schema_name"], open_only=True) == []


def test_banned_interest_rejected(app, client):
    """Une passion interdite est refusée au profil et purgée des profils."""
    s = mk_session("res-mo-e")
    a = mk_user(s["schema_name"], "a@e.local", interests=["bingo", "drogue"])
    # L'intervenant interdit "drogue" → retirée de tous les profils
    assert matching.add_banned(s["schema_name"], "Drogue") == "drogue"
    assert matching.user_interests_for(s["schema_name"], a) == ["bingo"]
    # Nouvelle tentative d'ajout : ignorée
    clean = matching.set_user_interests(s["schema_name"], a,
                                        ["drogue", "marche"])
    assert clean == ["marche"]
    # Réautoriser → réutilisable
    matching.remove_banned(s["schema_name"], "drogue")
    clean = matching.set_user_interests(s["schema_name"], a, ["drogue"])
    assert clean == ["drogue"]


def test_admin_catalog(app, client):
    s = mk_session("res-mo-f")
    mk_admin(s["id"], "int@f.local", otp="4444")
    login_admin(client, "res-mo-f", "int@f.local", "4444")
    post(client, "/res-mo-f/admin/passions", "/res-mo-f/admin/passions",
         data={"action": "catalog_add", "name": "Pétanque"})
    assert matching.list_catalog(s["schema_name"]) == ["petanque"]
    # Le catalogue interdit ne peut pas être ajouté
    matching.add_banned(s["schema_name"], "drogue")
    post(client, "/res-mo-f/admin/passions", "/res-mo-f/admin/passions",
         data={"action": "catalog_add", "name": "drogue"})
    assert "drogue" not in matching.list_catalog(s["schema_name"])
