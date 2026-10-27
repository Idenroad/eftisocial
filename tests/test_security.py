"""Tests sécurité : en-têtes CSP, CSRF obligatoire, XSS, cookies."""

import re

from .conftest import (csrf_of, login_user, mk_session, mk_user, post)


def test_security_headers(app, client):
    resp = client.get("/")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Cache-Control"] == "no-store"


def test_csrf_required_on_post(app, client):
    """Un POST sans token CSRF est refusé (400)."""
    s = mk_session("res-sec-a")
    mk_user(s["schema_name"], "u@a.local", otp="111111")
    resp = client.post("/res-sec-a/connexion",
                       data={"email": "u@a.local"})
    assert resp.status_code == 400


def test_csrf_required_on_api(app, client):
    s = mk_session("res-sec-b")
    uid = mk_user(s["schema_name"], "u@b.local", otp="111111")
    login_user(client, "res-sec-b", "u@b.local", "111111")
    resp = client.post("/res-sec-b/api/swipe",
                       json={"target": uid, "action": "like"})
    assert resp.status_code == 400


def test_xss_escaped_in_templates(app, client):
    """Les données usager sont échappées (Jinja autoescape)."""
    s = mk_session("res-sec-c")
    uid = mk_user(s["schema_name"], "u@c.local", otp="111111")
    from app.db import sess_conn
    with sess_conn(s["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET bio='<script>alert(1)</script>' "
                        "WHERE id=%s", (uid,))
    login_user(client, "res-sec-c", "u@c.local", "111111")
    html = client.get("/res-sec-c/mon-profil").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_session_cookie_flags(app, client):
    s = mk_session("res-sec-d")
    mk_user(s["schema_name"], "u@d.local", otp="111111")
    resp = login_user(client, "res-sec-d", "u@d.local", "111111")
    set_cookie = resp.headers.get("Set-Cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=Lax" in set_cookie
    assert "efti_user=" in set_cookie


def test_slug_injection_rejected(app):
    """Un slug malveillant ne produit jamais un schéma SQL injectable."""
    from app.db import get_session_by_slug, schema_for
    import pytest
    for bad in ["a'; DROP TABLE users--", "../etc", "a b", "", "x"]:
        if bad == "x":
            continue  # 'x' est un slug valide
        assert get_session_by_slug(bad) is None
        with pytest.raises(ValueError):
            schema_for(bad)


def test_media_requires_auth(app, client):
    s = mk_session("res-sec-e")
    resp = client.get(
        "/res-sec-e/media/profils/00000000-0000-0000-0000-000000000000/x.webp")
    assert resp.status_code == 403


def test_otp_single_use(app, client):
    """Un code OTP déjà utilisé ne fonctionne plus (invariant métier)."""
    s = mk_session("res-sec-f")
    mk_user(s["schema_name"], "u@f.local", otp="111111")
    from app import auth
    code, _ = auth.request_otp("u@f.local", "user", s["id"], "1.2.3.4")
    assert auth.verify_otp("u@f.local", "user", s, code) is True
    # Réutilisation : refusée (code marqué used)
    assert auth.verify_otp("u@f.local", "user", s, code) is False
    # Un mauvais code aussi
    assert auth.verify_otp("u@f.local", "user", s, "000000") is False


def test_otp_max_attempts(app, client):
    """Après OTP_MAX_ATTEMPTS essais ratés, même le bon code est refusé."""
    s = mk_session("res-sec-g")
    mk_user(s["schema_name"], "u@g.local", otp="111111")
    from app import auth
    code, _ = auth.request_otp("u@g.local", "user", s["id"], "1.2.3.4")
    for _ in range(app.config["OTP_MAX_ATTEMPTS"]):
        assert auth.verify_otp("u@g.local", "user", s, "000000") is False
    assert auth.verify_otp("u@g.local", "user", s, code) is False
