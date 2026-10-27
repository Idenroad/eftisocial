#!/usr/bin/env python3
"""CLI EftiSocial — gestion de l'installation et des données.

Usage:
  python cli.py initdb                      # schéma core + catalogue
  python cli.py create-session "Nom"        # nouvelle résidence
  python cli.py create-superadmin EMAIL --first-name P --last-name N
  python cli.py seed-demo                   # données de démonstration
  python cli.py serve [--host H --port P]   # serveur dev (prod: gunicorn)
"""

import argparse
import sys

from app import create_app
from app.db import (core_conn, create_session, init_core_db, list_sessions,
                    slugify)

# Intérêts suggérés (catalogue d'aide pour les aînés)
INTERETS = [
    "Marche", "Jardinage", "Bingo", "Cartes", "Cuisine", "Lecture",
    "Tricot", "Peinture", "Musique", "Chant", "Danse", "Pétanque",
    "Échecs", "Scrabble", "Cinéma", "Photographie", "Pêche", "Oiseaux",
    "Histoire", "Généalogie", "Artisanat", "Bénévolat", "Yoga doux",
    "Aquaforme", "Voyages", "Théâtre", "Casse-tête", "Ordinateur",
    "Prière", "Nature",
]


def cmd_initdb(_args):
    app = create_app()
    with app.app_context():
        init_core_db()
        with core_conn() as conn:
            with conn.cursor() as cur:
                for i in INTERETS:
                    cur.execute(
                        "INSERT INTO core.interests (name, label) "
                        "VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                        (i.lower(), i))
    print("Base initialisée (schéma core + catalogue d'intérêts).")


def cmd_create_session(args):
    app = create_app()
    with app.app_context():
        slug = slugify(args.name)
        row = create_session(slug, args.name)
        print(f"Session créée : {row['name']} -> /{row['slug']} "
              f"(schéma {row['schema_name']})")


def cmd_create_superadmin(args):
    app = create_app()
    with app.app_context():
        with core_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO core.superadmins (email, first_name, last_name) "
                    "VALUES (%s,%s,%s) ON CONFLICT (email) DO UPDATE "
                    "SET first_name = EXCLUDED.first_name "
                    "RETURNING id",
                    (args.email, args.first_name, args.last_name or ""))
                row = cur.fetchone()
        print(f"Superadmin : {args.email} (id {row['id']})")


def cmd_seed_demo(_args):
    app = create_app()
    with app.app_context():
        from app.seed_demo import seed_demo
        seed_demo()


def cmd_serve(args):
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)


def main():
    p = argparse.ArgumentParser(prog="eftisocial")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("initdb").set_defaults(f=cmd_initdb)

    c = sub.add_parser("create-session")
    c.add_argument("name")
    c.set_defaults(f=cmd_create_session)

    c = sub.add_parser("create-superadmin")
    c.add_argument("email")
    c.add_argument("--first-name", default="Super")
    c.add_argument("--last-name", default="Admin")
    c.set_defaults(f=cmd_create_superadmin)

    sub.add_parser("seed-demo").set_defaults(f=cmd_seed_demo)

    c = sub.add_parser("serve")
    c.add_argument("--host", default="127.0.0.1")
    c.add_argument("--port", type=int, default=5000)
    c.add_argument("--debug", action="store_true")
    c.set_defaults(f=cmd_serve)

    args = p.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
