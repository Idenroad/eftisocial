"""Tests d'upload et gestion des photos de profil."""

import io

import pytest
from PIL import Image

from .conftest import login_user, mk_session, mk_user, post


def _png_bytes(color="#006847"):
    img = Image.new("RGB", (64, 64), color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def _upload(client, slug, fileobj, filename="p.png", ctype="image/png"):
    from .conftest import csrf_of
    tok = csrf_of(client, f"/{slug}/mon-profil")
    return client.post(
        f"/{slug}/mon-profil/photos",
        data={"csrf_token": tok,
              "photo": (fileobj, filename, ctype)},
        content_type="multipart/form-data")


def test_photo_upload(app, client):
    s = mk_session("res-ph-a")
    uid = mk_user(s["schema_name"], "u@a.local", otp="111111")
    login_user(client, "res-ph-a", "u@a.local", "111111")
    resp = _upload(client, "res-ph-a", _png_bytes())
    assert resp.status_code == 302

    from app.photos import list_photos
    photos = list_photos(s["schema_name"], uid)
    assert len(photos) == 1 and photos[0]["is_primary"] is True
    assert photos[0]["filename"].endswith(".webp")

    # Le fichier existe dans le répertoire de la session
    from app.db import profile_dir
    assert (profile_dir("res-ph-a", uid) / photos[0]["filename"]).is_file()


def test_photo_rejects_non_image(app, client):
    s = mk_session("res-ph-b")
    uid = mk_user(s["schema_name"], "u@b.local", otp="111111")
    login_user(client, "res-ph-b", "u@b.local", "111111")
    resp = _upload(client, "res-ph-b", io.BytesIO(b"<html><script>x"),
                   filename="evil.png")
    assert resp.status_code == 400
    from app.photos import list_photos
    assert list_photos(s["schema_name"], uid) == []


def test_photo_limit(app, client):
    """Max MAX_EXTRA_PHOTOS+1 photos par profil."""
    s = mk_session("res-ph-c")
    uid = mk_user(s["schema_name"], "u@c.local", otp="111111")
    login_user(client, "res-ph-c", "u@c.local", "111111")
    max_n = app.config["MAX_EXTRA_PHOTOS"] + 1
    for _ in range(max_n):
        assert _upload(client, "res-ph-c", _png_bytes()).status_code == 302
    resp = _upload(client, "res-ph-c", _png_bytes())
    assert resp.status_code == 400
    assert b"Maximum" in resp.data


def test_delete_photo_reassigns_primary(app, client):
    s = mk_session("res-ph-d")
    uid = mk_user(s["schema_name"], "u@d.local", otp="111111")
    login_user(client, "res-ph-d", "u@d.local", "111111")
    _upload(client, "res-ph-d", _png_bytes())
    _upload(client, "res-ph-d", _png_bytes("#CE1126"), filename="q.png")

    from app.photos import list_photos
    ph = list_photos(s["schema_name"], uid)
    assert len(ph) == 2 and ph[0]["is_primary"]
    primary_id = ph[0]["id"]

    from .conftest import csrf_of
    tok = csrf_of(client, "/res-ph-d/mon-profil")
    client.post(f"/res-ph-d/mon-profil/photos/{primary_id}/supprimer",
                data={"csrf_token": tok})
    ph = list_photos(s["schema_name"], uid)
    assert len(ph) == 1 and ph[0]["is_primary"] is True


def test_delete_account_removes_photos(app, client):
    """Suppression de compte : le répertoire photos est effacé."""
    s = mk_session("res-ph-e")
    uid = mk_user(s["schema_name"], "u@e.local", otp="111111")
    login_user(client, "res-ph-e", "u@e.local", "111111")
    _upload(client, "res-ph-e", _png_bytes())

    from app.db import profile_dir
    pdir = profile_dir("res-ph-e", uid)
    assert pdir.is_dir()

    from .conftest import csrf_of
    tok = csrf_of(client, "/res-ph-e/mon-profil")
    client.post("/res-ph-e/mon-profil/supprimer",
                data={"csrf_token": tok, "confirm": "oui"})
    assert not pdir.exists()
