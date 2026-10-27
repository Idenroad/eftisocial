"""Configuration EftiSocial.

Charge les variables depuis .env (racine du projet ou $DATA_DIR/.env).
Toutes les valeurs sensibles viennent de l'environnement — jamais codées en dur.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Ordre de recherche du .env : $EFTISOCIAL_ENV > racine projet > $DATA_DIR/.env
_env_candidates = [
    os.environ.get("EFTISOCIAL_ENV"),
    BASE_DIR / ".env",
]
_data_dir_env = os.environ.get("DATA_DIR")
if _data_dir_env:
    _env_candidates.append(Path(_data_dir_env) / ".env")

for _c in _env_candidates:
    if _c and Path(_c).is_file():
        load_dotenv(_c, override=False)
        break


def _bool(name: str, default: bool = False) -> bool:
    """Lit un booléen d'environnement (True/False/1/0/oui/non)."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "o", "oui", "on")


class Config:
    """Paramètres globaux de l'application."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    DATABASE_URL = os.environ.get(
        "DATABASE_URL", "postgresql://postgres@localhost:5432/eftisocial"
    )
    DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))

    # SMTP
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587") or 587)
    MAIL_USE_TLS = _bool("MAIL_USE_TLS", True)
    MAIL_USE_SSL = _bool("MAIL_USE_SSL", False)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "") or os.environ.get(
        "MAIL_USERNAME", ""
    )

    # Mode démo : OTP statiques, envoi courriel contourné
    DEMO_MODE = _bool("DEMO_MODE", False)

    # Cookies / proxy
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    TRUST_PROXY = _bool("TRUST_PROXY", False)
    PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")

    # OTP
    OTP_TTL_SECONDS = int(os.environ.get("OTP_TTL_SECONDS", "600"))  # 10 min
    OTP_MAX_ATTEMPTS = 5
    OTP_REQUEST_LIMIT_PER_HOUR = 10  # par courriel

    # Jetons de session (DB-backed)
    TOKEN_TTL_HOURS = 12          # sans "rester connecté"
    TOKEN_TTL_REMEMBER_DAYS = 30  # avec "rester connecté"

    # Photos
    MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 Mo en entrée
    PHOTO_MAX_DIM = 1200                # redimensionnement
    MAX_EXTRA_PHOTOS = 5

    # Divers
    MAX_INTERESTS = 10
    JSON_AS_ASCII = False


class TestConfig(Config):
    """Configuration de test : cookies non-Secure, CSRF géré par test."""

    SESSION_COOKIE_SECURE = False
    DEMO_MODE = True
