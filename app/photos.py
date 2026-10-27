"""Gestion des photos de profil.

Validation stricte : le fichier est décodé par Pillow (les fichiers
tronqués/non-images sont rejetés), ré-encodé en WebP et redimensionné.
Le nom de fichier est généré — jamais pris du client.
"""

import io
import uuid
from pathlib import Path

from PIL import Image
from flask import abort, current_app, send_file

from .db import profile_dir, profiles_dir, sess_conn

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}


class PhotoError(Exception):
    """Erreur de validation photo (message sûr à afficher à l'usager)."""


def _open_image(stream) -> Image.Image:
    try:
        img = Image.open(stream)
        img.verify()  # décode l'en-tête — rejette les faux fichiers
        stream.seek(0)
        img = Image.open(stream)  # verify() invalide l'objet : on rouvre
    except Exception:
        raise PhotoError("Le fichier n'est pas une image valide.")
    if img.format not in ALLOWED_FORMATS:
        raise PhotoError("Format d'image non accepté.")
    return img


def list_photos(schema: str, user_id) -> list[dict]:
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, filename, is_primary, position FROM photos "
                "WHERE user_id = %s ORDER BY is_primary DESC, position, created_at",
                (str(user_id),))
            return [dict(r) for r in cur.fetchall()]


def save_photo(schema: str, slug: str, user_id, file_storage) -> dict:
    """Valide, convertit en WebP et enregistre une photo de profil."""
    cfg = current_app.config
    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > cfg["MAX_PHOTO_BYTES"]:
        raise PhotoError("Photo trop volumineuse (max 10 Mo).")
    if size == 0:
        raise PhotoError("Fichier vide.")

    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n, coalesce(bool_or(is_primary), false) AS has_primary "
                "FROM photos WHERE user_id = %s", (str(user_id),))
            row = cur.fetchone()
            if row["n"] >= cfg["MAX_EXTRA_PHOTOS"] + 1:
                raise PhotoError(
                    f"Maximum {cfg['MAX_EXTRA_PHOTOS'] + 1} photos atteint.")

            img = _open_image(file_storage.stream).convert("RGB")
            img.thumbnail((cfg["PHOTO_MAX_DIM"], cfg["PHOTO_MAX_DIM"]),
                          Image.LANCZOS)

            photo_id = uuid.uuid4()
            filename = f"photo_{photo_id.hex[:12]}.webp"
            pdir = profile_dir(slug, user_id)
            pdir.mkdir(parents=True, exist_ok=True)
            img.save(pdir / filename, "WEBP", quality=82, method=4)

            is_primary = not row["has_primary"]
            cur.execute(
                "INSERT INTO photos (id, user_id, filename, is_primary, position) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id, filename, is_primary",
                (str(photo_id), str(user_id), filename, is_primary, row["n"]))
            return dict(cur.fetchone())


def delete_photo(schema: str, slug: str, user_id, photo_id) -> bool:
    """Supprime une photo (fichier + ligne). La principale est réassignée."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM photos WHERE id = %s AND user_id = %s "
                "RETURNING filename, is_primary",
                (str(photo_id), str(user_id)))
            row = cur.fetchone()
            if not row:
                return False
            if row["is_primary"]:
                cur.execute(
                    "UPDATE photos SET is_primary = true WHERE id = ("
                    "  SELECT id FROM photos WHERE user_id = %s "
                    "  ORDER BY position, created_at LIMIT 1)",
                    (str(user_id),))
    fpath = profile_dir(slug, user_id) / row["filename"]
    if fpath.is_file():
        fpath.unlink()
    return True


def set_primary(schema: str, user_id, photo_id) -> bool:
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE photos SET is_primary = (id = %s) WHERE user_id = %s",
                (str(photo_id), str(user_id)))
            cur.execute(
                "SELECT 1 FROM photos WHERE id = %s AND user_id = %s",
                (str(photo_id), str(user_id)))
            return cur.fetchone() is not None


def primary_photo(schema: str, user_id) -> dict | None:
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT filename FROM photos WHERE user_id = %s "
                "ORDER BY is_primary DESC, position LIMIT 1",
                (str(user_id),))
            row = cur.fetchone()
    return dict(row) if row else None


def photo_path(slug: str, user_id, filename: str) -> Path:
    """Chemin fichier validé (anti-traversal) pour servir une photo."""
    pdir = profile_dir(slug, user_id).resolve()
    fpath = (pdir / filename).resolve()
    if pdir not in fpath.parents and fpath != pdir:
        raise PhotoError("Chemin invalide")
    return fpath


def delete_profile_dir(slug: str, user_id) -> None:
    """Supprime le répertoire photos d'un usager (suppression de compte)."""
    import shutil
    pdir = profile_dir(slug, user_id)
    if pdir.is_dir():
        shutil.rmtree(pdir)
