"""Tests i18n : sélecteur de langue, cookie, traductions EN/ES."""

from .conftest import login_user, mk_session, mk_user


def test_lang_param_renders_english(app, client):
    s = mk_session("res-lg-a")
    resp = client.get("/res-lg-a/connexion?lang=en")
    html = resp.get_data(as_text=True)
    assert "Sign in" in html and "6-digit code" in html
    # Le cookie lang est posé
    assert 'efti_lang=en' in resp.headers.get("Set-Cookie", "")


def test_lang_param_renders_spanish(app, client):
    mk_session("res-lg-b")
    html = client.get("/res-lg-b/connexion?lang=es").get_data(as_text=True)
    assert "Iniciar sesión" in html


def test_lang_cookie_persists(app, client):
    """Après ?lang=es, les pages suivantes restent en espagnol."""
    mk_session("res-lg-c")
    client.get("/res-lg-c/connexion?lang=es")
    html = client.get("/res-lg-c/connexion").get_data(as_text=True)
    assert "Iniciar sesión" in html


def test_lang_user_pages(app, client):
    s = mk_session("res-lg-d")
    mk_user(s["schema_name"], "u@d.local", otp="111111")
    login_user(client, "res-lg-d", "u@d.local", "111111")
    html = client.get("/res-lg-d/trouver?lang=en").get_data(as_text=True)
    assert "Discover" in html and "My matches" in html
    html = client.get("/res-lg-d/decouverte?lang=es").get_data(as_text=True)
    assert "Explorar" in html


def test_invalid_lang_falls_back(app, client):
    mk_session("res-lg-e")
    html = client.get("/res-lg-e/connexion?lang=de").get_data(as_text=True)
    assert "Connexion" in html  # français par défaut
