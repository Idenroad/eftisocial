"""Couche d'accès PostgreSQL pour EftiSocial.

Architecture multi-schémas :
  - schéma `core`         : données globales (sessions, admins, OTP, audit…)
  - schéma `sess_<slug>`  : données d'UNE résidence (users, swipes, events…)

L'étanchéité est garantie par le search_path : une connexion « session » ne
voit que son propre schéma + core. Impossible de lire une autre résidence.
"""

import re
import unicodedata
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SQL_DIR = Path(__file__).resolve().parent / "sql"

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
SCHEMA_RE = re.compile(r"^sess_[a-z0-9_]+$")

# Slugs réservés (jamais utilisables comme session)
RESERVED_SLUGS = {
    "superadmin", "admin", "static", "api", "auth", "media",
    "sw.js", "manifest.webmanifest", "favicon.ico", "demo",
}


def _database_url() -> str:
    """URL de la DB : config Flask si contexte actif, sinon env
    (DATABASE_URL_TEST en priorité — utilisé par la suite de tests)."""
    import os
    from flask import current_app, has_app_context

    if has_app_context():
        return current_app.config["DATABASE_URL"]
    return os.environ.get("DATABASE_URL_TEST") or os.environ["DATABASE_URL"]


def _data_dir() -> Path:
    import os
    from flask import current_app, has_app_context

    if has_app_context():
        return Path(current_app.config["DATA_DIR"])
    return Path(os.environ.get("DATA_DIR", "data"))


@contextmanager
def core_conn():
    """Connexion au schéma global. Commit auto à la sortie, rollback si erreur."""
    conn = psycopg.connect(_database_url(), autocommit=False, row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO core, public")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def sess_conn(schema_name: str):
    """Connexion confinée au schéma d'une session (+ core en lecture).

    Le nom de schéma est validé par regex stricte — aucune injection possible.
    """
    if not SCHEMA_RE.match(schema_name or ""):
        raise ValueError(f"Nom de schéma invalide: {schema_name!r}")
    conn = psycopg.connect(_database_url(), autocommit=False, row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            # search_path littéral : le nom a passé la regex, sûr à interpoler
            cur.execute(f"SET search_path TO {schema_name}, core, public")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── Utilitaires de nommage ────────────────────────────────────────────────────

def slugify(name: str) -> str:
    """'Résidence Manoir' -> 'residence-manoir' (ASCII, minuscules, tirets)."""
    norm = unicodedata.normalize("NFKD", name)
    ascii_name = norm.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not SLUG_RE.match(slug):
        raise ValueError(f"Slug invalide dérivé de {name!r}: {slug!r}")
    if slug in RESERVED_SLUGS:
        raise ValueError(f"Slug réservé: {slug!r}")
    return slug


def schema_for(slug: str) -> str:
    """'residence-manoir' -> 'sess_residence_manoir'"""
    if not SLUG_RE.match(slug or ""):
        raise ValueError(f"Slug invalide: {slug!r}")
    return "sess_" + slug.replace("-", "_")


def normalize_interest(label: str) -> str:
    """Normalise un intérêt : minuscules, sans accents, trim."""
    norm = unicodedata.normalize("NFKD", label.strip())
    ascii_i = norm.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_i.lower()).strip()


# ─── Répertoires de données par session ───────────────────────────────────────
#   DATA_DIR/<slug>/profils/<user_uuid>/photo_N.webp
#   DATA_DIR/<slug>/evenements/<event_uuid>/

def session_dir(slug: str) -> Path:
    return _data_dir() / slug


def profiles_dir(slug: str) -> Path:
    return session_dir(slug) / "profils"


def profile_dir(slug: str, user_id) -> Path:
    return profiles_dir(slug) / str(user_id)


def events_dir(slug: str) -> Path:
    return session_dir(slug) / "evenements"


def event_dir(slug: str, event_id) -> Path:
    return events_dir(slug) / str(event_id)


# ─── Provisionnement ──────────────────────────────────────────────────────────

def init_core_db(conn=None):
    """Crée le schéma core + extension citext + catalogue d'intérêts."""
    ddl = (SQL_DIR / "core.sql").read_text(encoding="utf-8")

    def _apply(c):
        with c.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS citext")
            cur.execute(ddl)

    if conn is not None:
        _apply(conn)
        conn.commit()
    else:
        raw = psycopg.connect(_database_url(), autocommit=True)
        try:
            with raw.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS citext")
                cur.execute(ddl)
        finally:
            raw.close()


def create_session(slug: str, name: str) -> dict:
    """Crée une session : ligne core.sessions + schéma dédié + répertoires."""
    if not SLUG_RE.match(slug or "") or slug in RESERVED_SLUGS:
        raise ValueError(f"Slug invalide ou réservé: {slug!r}")
    schema = schema_for(slug)
    ddl = (SQL_DIR / "session.sql").read_text(encoding="utf-8").replace("{schema}", schema)

    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO core.sessions (slug, name, schema_name) "
                "VALUES (%s, %s, %s) RETURNING id, slug, name, schema_name",
                (slug, name, schema),
            )
            row = cur.fetchone()
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            cur.execute(ddl)

    profiles_dir(slug).mkdir(parents=True, exist_ok=True)
    events_dir(slug).mkdir(parents=True, exist_ok=True)
    return dict(row)


def delete_session(slug: str) -> None:
    """Supprime une session : schéma DROP CASCADE + ligne + répertoires.

    L'appelant doit journaliser AVANT l'appel (audit_log.session_id est un
    simple uuid sans FK — le log survit à la suppression).
    """
    import shutil

    schema = schema_for(slug)
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            cur.execute("DELETE FROM core.sessions WHERE slug = %s", (slug,))

    sdir = session_dir(slug)
    if sdir.is_dir():
        shutil.rmtree(sdir)


def get_session_by_slug(slug: str) -> dict | None:
    """Retourne la session active correspondant au slug, ou None."""
    if not SLUG_RE.match(slug or ""):
        return None
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, slug, name, schema_name, active FROM core.sessions "
                "WHERE slug = %s",
                (slug,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def get_session_by_id(session_id) -> dict | None:
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, slug, name, schema_name, active FROM core.sessions "
                "WHERE id = %s",
                (str(session_id),),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def list_sessions() -> list[dict]:
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, slug, name, schema_name, active, created_at "
                "FROM core.sessions ORDER BY name"
            )
            return [dict(r) for r in cur.fetchall()]
