"""Données de démonstration EftiSocial.

Session « residence-demo » :
  - intervenant : intervenant@demo.local, OTP statique 444
  - membres     : jc@demo.local (111111), alex@demo.local (222222),
                  lugus@demo.local (333333)
  - photos      : demo/jc.webp, demo/alex.webp, demo/lugus.webp
  - événements  : créés par l'intervenant

Idempotent : si la session existe déjà, rien n'est dupliqué.
"""

import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import (core_conn, create_session, event_dir, get_session_by_slug,
                 profile_dir, sess_conn, slugify)
from . import matching

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"
SLUG = "residence-demo"

USERS = [
    {"email": "jc@demo.local", "first_name": "JC", "sex": "M",
     "otp": "111111", "photo": "jc.webp",
     "interests": ["marche", "jardinage", "bingo", "cuisine", "histoire"],
     "bio": "Amateur de bonnes marches et de cuisine maison."},
    {"email": "alex@demo.local", "first_name": "Alex", "sex": "F",
     "otp": "222222", "photo": "alex.webp",
     "interests": ["marche", "jardinage", "bingo", "peinture", "lecture"],
     "bio": "J'aime peindre et jardiner."},
    {"email": "lugus@demo.local", "first_name": "Lugus", "sex": "M",
     "otp": "333333", "photo": "lugus.webp",
     "interests": ["marche", "jardinage", "bingo", "musique", "echecs"],
     "bio": "Musicien à la retraite, joueur d'échecs."},
]

ADMIN = {"email": "intervenant@demo.local", "first_name": "Intervenant",
         "otp": "444"}

EVENTS = [
    {"title": "Bingo du vendredi", "location": "Salle commune",
     "description": "Soirée bingo avec petits prix et collation.",
     "days": 3, "hour": 19},
    {"title": "Marche au parc", "location": "Entrée principale",
     "description": "Marche douce en groupe, tous niveaux bienvenus.",
     "days": 1, "hour": 9},
    {"title": "Atelier jardinage", "location": "Jardin intérieur",
     "description": "On plante les semis du printemps ensemble.",
     "days": 5, "hour": 14},
]


def seed_demo() -> dict:
    """Crée la session démo si absente. Retourne le résumé."""
    existing = get_session_by_slug(SLUG)
    if existing:
        print(f"Session démo déjà présente : /{SLUG} — rien à faire.")
        return existing

    session = create_session(SLUG, "Résidence Démo")
    sid, schema = session["id"], session["schema_name"]
    now = datetime.now(timezone.utc)

    # Intervenant avec OTP statique
    with core_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO core.admins (session_id, email, first_name, demo_otp) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (sid, ADMIN["email"], ADMIN["first_name"], ADMIN["otp"]))
            admin_id = cur.fetchone()["id"]

    # Membres + photos + intérêts
    uids = {}
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            for u in USERS:
                uid = uuid.uuid4()
                cur.execute(
                    "INSERT INTO users (id, email, first_name, sex, bio, "
                    "demo_otp, created_by) VALUES (%s,%s,%s,%s,%s,%s,'admin')",
                    (str(uid), u["email"], u["first_name"], u["sex"],
                     u["bio"], u["otp"]))
                # Photo : on copie le webp démo
                src = DEMO_DIR / u["photo"]
                pdir = profile_dir(SLUG, uid)
                pdir.mkdir(parents=True, exist_ok=True)
                dest = pdir / f"photo_{uid.hex[:12]}.webp"
                shutil.copyfile(src, dest)
                cur.execute(
                    "INSERT INTO photos (user_id, filename, is_primary) "
                    "VALUES (%s,%s,true)", (str(uid), dest.name))
                uids[u["email"]] = uid

            # Événements (créés par l'intervenant)
            for e in EVENTS:
                event_at = now + timedelta(days=e["days"])
                event_at = event_at.replace(hour=e["hour"], minute=0,
                                            second=0, microsecond=0)
                cur.execute(
                    "INSERT INTO events (title, description, location, "
                    "event_at, creator_role, creator_id, creator_name) "
                    "VALUES (%s,%s,%s,%s,'admin',%s,%s) RETURNING id",
                    (e["title"], e["description"], e["location"],
                     event_at, str(admin_id), ADMIN["first_name"]))
                eid = cur.fetchone()["id"]
                event_dir(SLUG, eid).mkdir(parents=True, exist_ok=True)

    for u in USERS:
        matching.set_user_interests(schema, uids[u["email"]], u["interests"])

    print("Démo créée :")
    print(f"  Session       : /{SLUG}")
    for u in USERS:
        print(f"  Membre        : {u['email']}  OTP {u['otp']}")
    print(f"  Intervenant   : {ADMIN['email']}  OTP {ADMIN['otp']}")
    return session
