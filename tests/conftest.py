"""Fixtures pytest — EftiSocial.

La suite exige une base PostgreSQL de test dédiée :
  DATABASE_URL_TEST=postgresql://postgres@localhost:5432/eftisocial_test

Chaque run repart d'un schéma core vierge (DROP CASCADE) — les schémas de
sessions de test sont créés/supprimés dynamiquement.
"""

import os
import re
import uuid

import psycopg
import pytest

from app import create_app
from app.config import Config

TEST_DB = os.environ.get(
    "DATABASE_URL_TEST",
    "postgresql://postgres@localhost:5432/eftisocial_test")


class _TestConfig(Config):
    DATABASE_URL = TEST_DB
    DATA_DIR = "/tmp/eftisocial_test_data"
    DEMO_MODE = True
    WTF_CSRF_ENABLED = True
    TESTING = True


def _reset_db():
    """Remet la base de test à zéro (tous schémas)."""
    conn = psycopg.connect(TEST_DB, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE 'sess\\_%' OR schema_name = 'core'")
            for r in cur.fetchall():
                cur.execute(f'DROP SCHEMA IF EXISTS "{r[0]}" CASCADE')
    finally:
        conn.close()


@pytest.fixture()
def app(tmp_path, monkeypatch):
    _reset_db()
    # DATA_DIR en env : les helpers DB (hors contexte Flask) l'utilisent aussi
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL_TEST", TEST_DB)
    cfg = _TestConfig()
    cfg.DATA_DIR = str(tmp_path / "data")
    application = create_app(cfg)
    # NB : PAS d'app_context() persisté — g (cache du token CSRF de
    # flask_wtf) y survivrait entre requêtes et contaminerait les clients.
    with application.app_context():
        from app.db import init_core_db
        init_core_db()
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


# ─── Helpers de création ──────────────────────────────────────────────────────

def mk_session(slug: str) -> dict:
    """Crée une session de test (schéma + répertoires)."""
    from app.db import create_session
    return create_session(slug, f"Résidence {slug}")


def mk_user(schema: str, email: str, first_name: str = "Test",
            sex: str = "F", otp: str = "123456",
            interests: list | None = None) -> str:
    """Insère un usager avec OTP statique. Retourne l'uuid."""
    from app import matching
    from app.db import sess_conn
    uid = uuid.uuid4()
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (id, email, first_name, sex, demo_otp) "
                "VALUES (%s,%s,%s,%s,%s)",
                (str(uid), email, first_name, sex, otp))
    if interests:
        matching.set_user_interests(schema, uid, interests)
    return str(uid)


def mk_admin(session_id, email: str, otp: str = "654321") -> str:
    """Insère un intervenant avec OTP statique. Retourne l'uuid."""
    from app.db import core_conn
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO core.admins (session_id, email, first_name, "
                "demo_otp) VALUES (%s,%s,'Admin',%s) RETURNING id",
                (str(session_id), email, otp))
            return str(cur.fetchone()["id"])


def mk_superadmin(email: str = "sa@test.local", otp: str = "999999") -> str:
    from app.db import core_conn
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO core.superadmins (email, first_name, demo_otp) "
                "VALUES (%s,'SA',%s) RETURNING id", (email, otp))
            return str(cur.fetchone()["id"])


def csrf_of(client, url: str) -> str:
    """Extrait le token CSRF d'une page GET (meta tag)."""
    resp = client.get(url)
    m = re.search(r'name="csrf-token" content="([^"]+)"',
                  resp.get_data(as_text=True))
    return m.group(1) if m else ""


def post(client, url: str, csrf_url: str, **kwargs):
    """POST avec token CSRF extrait d'une page GET préalable."""
    kwargs.setdefault("data", {})
    kwargs["data"]["csrf_token"] = csrf_of(client, csrf_url)
    return client.post(url, **kwargs)


def login_user(client, slug: str, email: str, code: str):
    """Flux complet de connexion usager via le client de test."""
    post(client, f"/{slug}/connexion", f"/{slug}/connexion",
         data={"email": email})
    return post(client, f"/{slug}/connexion/verification",
                f"/{slug}/connexion/verification",
                data={"code": code, "remember": "1"})


def login_admin(client, slug: str, email: str, code: str):
    post(client, f"/{slug}/admin/connexion", f"/{slug}/admin/connexion",
         data={"email": email})
    return post(client, f"/{slug}/admin/connexion/verification",
                f"/{slug}/admin/connexion/verification",
                data={"code": code})


def login_superadmin(client, email: str, code: str):
    post(client, "/superadmin/connexion", "/superadmin/connexion",
         data={"email": email})
    return post(client, "/superadmin/connexion/verification",
                "/superadmin/connexion/verification",
                data={"code": code})
