"""Tests d'étanchéité entre sessions (résidences).

Un compte créé dans /res-a ne doit pouvoir ni se connecter ni agir dans
/res-b. Même un jeton valide de A est rejeté par B (double contrôle :
session_id du jeton + schéma PostgreSQL dédié).
"""

from .conftest import (csrf_of, login_admin, login_user, mk_admin, mk_session,
                       mk_user, post)


def test_user_cannot_login_other_session(app, client):
    mk_session("res-iso-a")
    sb = mk_session("res-iso-b")
    mk_user(sb["schema_name"], "membre@b.local", otp="111111")
    # Ce courriel n'existe pas dans res-iso-a : OTP refusé
    resp = login_user(client, "res-iso-a", "membre@b.local", "111111")
    assert b"invalide" in resp.data.lower() or resp.status_code in (302, 200)
    # Jamais connecté à res-iso-a
    assert client.get("/res-iso-a/trouver").status_code == 302


def test_token_rejected_in_other_session(app, client):
    sa = mk_session("res-iso-c")
    mk_session("res-iso-d")
    mk_user(sa["schema_name"], "membre@c.local", otp="111111")
    login_user(client, "res-iso-c", "membre@c.local", "111111")
    # Le cookie efti_user (path=/res-iso-c) n'est pas envoyé à /res-iso-d,
    # mais même forcé, le jeton porte le mauvais session_id.
    tok = client.get_cookie("efti_user", path="/res-iso-c")
    assert tok is not None
    client.set_cookie("efti_user", tok.value, path="/res-iso-d")
    resp = client.get("/res-iso-d/api/deck")
    assert resp.status_code == 302


def test_media_not_accessible_other_session(app, client, tmp_path):
    """Une photo de res-iso-e n'est pas lisible depuis res-iso-f."""
    import io
    from PIL import Image

    se = mk_session("res-iso-e")
    mk_session("res-iso-f")
    uid = mk_user(se["schema_name"], "ph@e.local", otp="111111")

    # Dépose une photo directement dans le répertoire + DB
    from app.db import profile_dir, sess_conn
    img = Image.new("RGB", (32, 32), "#006847")
    buf = io.BytesIO()
    img.save(buf, "WEBP")
    pdir = profile_dir("res-iso-e", uid)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "photo_test.webp").write_bytes(buf.getvalue())
    with sess_conn(se["schema_name"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO photos (user_id, filename, is_primary) "
                "VALUES (%s,'photo_test.webp',true)", (uid,))

    # Non connecté : refus
    resp = client.get(
        f"/res-iso-e/media/profils/{uid}/photo_test.webp")
    assert resp.status_code == 403

    # Connecté dans une AUTRE session : refus
    sf_uid = mk_user(mk_session("res-iso-g")["schema_name"],
                     "x@g.local", otp="111111")
    login_user(client, "res-iso-g", "x@g.local", "111111")
    resp = client.get(f"/res-iso-e/media/profils/{uid}/photo_test.webp")
    assert resp.status_code == 403

    # Connecté dans la BONNE session : OK
    login_user(client, "res-iso-e", "ph@e.local", "111111")
    resp = client.get(f"/res-iso-e/media/profils/{uid}/photo_test.webp")
    assert resp.status_code == 200


def test_admin_cannot_admin_other_session(app, client):
    """L'intervenant de res-iso-h n'a aucun pouvoir dans res-iso-i."""
    sh = mk_session("res-iso-h")
    si = mk_session("res-iso-i")
    mk_admin(sh["id"], "int@h.local", otp="4444")
    mk_user(si["schema_name"], "u@i.local", otp="111111")

    login_admin(client, "res-iso-h", "int@h.local", "4444")
    # Liste des membres de l'autre session : redirigé vers login admin
    resp = client.get("/res-iso-i/admin/utilisateurs")
    assert resp.status_code == 302
    resp = client.post("/res-iso-i/admin/utilisateurs", data={})
    assert resp.status_code in (302, 400, 403)


def test_session_data_in_separate_schemas(app):
    """Vérification bas niveau : les users vivent dans des schémas distincts."""
    sa = mk_session("res-iso-j")
    sb = mk_session("res-iso-k")
    ua = mk_user(sa["schema_name"], "j@a.local")
    mk_user(sb["schema_name"], "k@b.local")

    import psycopg
    conn = psycopg.connect(app.config["DATABASE_URL"], autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {sa['schema_name']}.users")
            assert cur.fetchone()[0] == 1
            cur.execute(f"SELECT count(*) FROM {sb['schema_name']}.users")
            assert cur.fetchone()[0] == 1
            # L'usager de A n'existe PAS dans le schéma de B
            cur.execute(
                f"SELECT count(*) FROM {sb['schema_name']}.users "
                "WHERE email = 'j@a.local'")
            assert cur.fetchone()[0] == 0
    finally:
        conn.close()
