# EftiSocial

> Application de rencontres pour aînés en résidences — **MVP open source**.
> Projet original basé sur les idées de **Eftivali Gomez**.
> Licence : **AGPLv3** (voir `LICENSE`).

EftiSocial aide les résidents de maisons de retraite et résidences pour aînés
à se rencontrer : matching par passions communes (style swipe), découverte
par intérêts, événements de la résidence et tchat entre matchs. Conçu pour
les aînés : grosses cibles tactiles, texte large, parcours ultra simple,
connexion sans mot de passe (code envoyé par courriel).

PWA « mobile only » : installable sur l'écran d'accueil du téléphone.
Interface trilingue : **français, anglais, espagnol**.

---

## ⚠️ Statut

Ceci est un **MVP** (minimum viable product) fonctionnel mais pas un produit
fini : il est fait pour être testé, démontré et par la suite évoler. Voir la section
« Limites connues » avant tout usage réel.

---

## Fonctionnalités

### Membre (résident) — `/<résidence>/`

| Onglet | Fonction |
|---|---|
| **Trouver** | Pile de profils à swiper (tactile ou boutons ✕/♥), classée par nombre de passions communes. Like réciproque → **match** instantané. |
| **Matchs** | Liste des matchs avec badge de messages non lus. |
| **Tchat** | Messagerie temps réel (polling 4 s) réservée aux deux membres du match. |
| **Découverte** | Toutes les passions de la résidence avec compteurs de membres, recherche, filtre « mes passions ». |
| **Événements** | Événements de la résidence (créés par intervenants, superadmin ou membres), inscription/désinscription, capacité max, annulation par le créateur. |
| **Profil** | Photos (1 principale + 5 max), bio, sexe, max 10 passions (suggestions du catalogue), pause de compte, membres bloqués, suppression de compte. |

Gestion des relations :

- **Supprimer un match** → les deux profils retournent dans le pool
  (contrairement à Tinder : rien n'est définitif).
- **Bloquer** → invisibilité mutuelle (deck, découverte, profil, tchat),
  réversible depuis « Mon profil ».
- **Signaler** → envoi d'un signalement (motif + détails) aux intervenants.

### Intervenant (admin de résidence) — `/<résidence>/admin/`

- Création, édition, pause et suppression des comptes membres
- Création/suppression d'événements
- **Signalements** : file des comportements rapportés, marquage « traité »
- **Passions** : catalogue suggéré de la résidence + **interdictions**
  (un mot interdit est refusé et purgé de tous les profils)
- **Journal d'audit** en lecture seule de la résidence

### Superadmin — `/superadmin/`

- Création et suppression de sessions (résidences) — chaque session obtient
  son schéma PostgreSQL et ses répertoires de données
- Activation/désactivation de sessions
- Création/suppression des intervenants par session
- Création/suppression d'événements dans toute session
- Journal d'audit global

---

## Architecture

### Stack

| Couche | Technologie |
|---|---|
| Backend | Python 3, Flask 3, Jinja2 |
| Serveur | gunicorn (`wsgi:app`) |
| DB | PostgreSQL (extension `citext`) |
| Frontend | Jinja2 server-side + JS vanilla (aucune dépendance) |
| PWA | manifest par session + service worker |
| Tests | pytest (75 tests) |

### Multi-tenant : un schéma PostgreSQL par résidence

```
core (schéma global)
├── sessions        — résidences (slug, nom, schema_name, active)
├── superadmins     — comptes superadmin (email, demo_otp)
├── admins          — intervenants rattachés à UNE session
├── otp_codes       — codes OTP (hashés, 10 min, 5 essais, usage unique)
├── auth_tokens     — jetons de session persistants (hashés)
├── audit_log       — journal IMMUABLE (trigger anti UPDATE/DELETE/TRUNCATE)
└── interests       — catalogue d'intérêts suggérés global

sess_<slug> (schéma par résidence — étanchéité totale)
├── users               — membres (email, prénom, sexe, bio, paused, demo_otp)
├── user_interests      — passions (max 10 par membre)
├── photos              — photos de profil (fichiers sur disque)
├── swipes              — like/pass (unique par paire)
├── matches             — matchs (paire ordonnée, unique)
├── messages            — tchat entre matchés
├── blocks              — blocages (invisibilité mutuelle)
├── reports             — signalements vers intervenants
├── session_interests   — catalogue de passions de la résidence
├── banned_interests    — passions interdites
├── events              — événements
└── event_participants  — inscriptions
```

Une connexion `sess_conn(schema)` fixe `search_path` sur le schéma de la
session : **impossible de lire une autre résidence** — ni par l'app, ni par
injection. Triple verrouillage côté auth : le jeton porte `session_id`, le
cookie est scopé par chemin (`/<slug>`), le schéma DB est dédié.

### Fichiers par session

```
DATA_DIR/
  <slug>/
    profils/<user_uuid>/photo_xxx.webp
    evenements/<event_uuid>/
```

Photos validées et ré-encodées WebP par Pillow (max 1200 px), noms générés
côté serveur, servies via route authentifiée (membre ou intervenant de la
session uniquement).

### Authentification

- **OTP par courriel uniquement** — pas de mot de passe.
- 3 rôles, 3 cookies scopés par chemin : `efti_sa` (`/superadmin`),
  `efti_admin` (`/<slug>/admin`), `efti_user` (`/<slug>`).
- Jetons persistants en DB (SHA-256 poivré `SECRET_KEY`), « rester connecté »
  = 30 jours, sinon 12 h. Révocation serveur possible.
- `demo_otp` : code statique par compte (démo/tests ; vide en production).

### Sécurité

- **CSP** stricte `default-src 'self'` — zéro JS/CSS inline.
- **CSRF** flask-wtf sur tous les POST (+ en-tête `X-CSRFToken` pour le JSON).
- **XSS** : autoescape Jinja + insertions DOM via `textContent`.
- Cookies `HttpOnly`, `SameSite=Lax`, `Secure` configurable.
- **Audit immuable** : `core.audit_log`, trigger PostgreSQL interdisant
  UPDATE/DELETE/TRUNCATE. Toute manipulation de compte/session/événement
  est consignée (acteur, action, cible, IP, détails JSON).
- Rate-limit OTP (10 demandes/h/courriel), 5 essais max par code.
- Slugs/schémas validés par regex — aucune interpolation SQL non bornée.

### i18n

`app/i18n.py` : dict français (source) → EN/ES ; `t()` en templates, `tr()`
en Python. Sélecteur FR/EN/ES en barre du haut → `?lang=` → cookie
`efti_lang` → Accept-Language → fr. Panneaux admin/superadmin en français.

### Structure du code

```
app/
├── __init__.py          — factory Flask, CSRF, sécurité, i18n
├── config.py            — .env (SECRET_KEY, DATABASE_URL, SMTP, DATA_DIR…)
├── db.py                — connexions core/session, provisioning schémas
├── auth.py              — OTP, jetons, cookies, décorateurs de rôle
├── audit.py             — journal immuable
├── mailer.py            — SMTP / mode démo
├── matching.py          — deck, swipes, matchs, tchat, blocks, reports,
│                          passions (catalogue + interdictions), intérêts
├── photos.py            — upload/validation/suppression photos
├── security.py          — en-têtes CSP & co
├── i18n.py              — traductions FR/EN/ES
├── seed_demo.py         — données de démonstration
├── sql/                 — DDL core.sql + session.sql (idempotents)
├── blueprints/          — root, user_app, session_admin, superadmin
├── templates/           — base + auth + user + admin + superadmin
└── static/              — css (couleurs Mexique), js, icons, sw.js
cli.py                   — initdb, create-session, create-superadmin,
                           seed-demo, serve
wsgi.py                  — point d'entrée gunicorn
install-eftisocial.sh    — installateur Debian 13 LXC
tests/                   — 75 tests pytest
demo/                    — photos + comptes de démo
```

---

## Démarrage rapide (développement)

```bash
pip install -r requirements.txt
cp .env.example .env          # éditer DATABASE_URL, DATA_DIR, SMTP…
python cli.py initdb
python cli.py create-superadmin vous@exemple.com --first-name Prénom
python cli.py seed-demo       # session /residence-demo
python cli.py serve --port 5000        # ou : gunicorn -b 127.0.0.1:5000 'wsgi:app'
```

Sans SMTP, mettre `DEMO_MODE=True` dans `.env` : les OTP sont imprimés
dans les logs du serveur.

### Comptes démo

| Compte | Rôle | OTP | Page |
|---|---|---|---|
| jc@demo.local | membre | 111111 | `/residence-demo/connexion` |
| alex@demo.local | membre | 222222 | idem |
| lugus@demo.local | membre | 333333 | idem |
| intervenant@demo.local | intervenant | 444 | `/residence-demo/admin/connexion` |

### Tests

```bash
export DATABASE_URL_TEST=postgresql://user:pass@localhost:5432/eftisocial_test
pytest            # 75 tests : auth, isolation, swipe/match, tchat,
                  # événements, admin, superadmin, audit, sécurité,
                  # photos, profil, modération, i18n
```

## Installation production (Debian 13 / LXC)

```bash
sudo bash install-eftisocial.sh [dossier-sources]
```

Installe python3-venv + PostgreSQL, crée venv + rôle/DB randomisés + DB de
test, configure `.env` (SECRET_KEY, SMTP optionnel), demande l'email
superadmin et **si la version démo doit être installée**, crée le service
systemd gunicorn, puis écrit `eftisocial_credentials.txt` (à supprimer après
lecture).

---

## Limites connues (MVP)

- Tchat = polling 4 s (pas de WebSocket) — voulu pour la simplicité.
- Notifications push / badges PWA non implémentés.
- Panneaux admin/superadmin non traduits (français seulement).
- Pas de redimensionnement côté client avant upload photo.
- Suppression de session = destructive (schéma + fichiers effacés,
  confirmation par saisie du slug ; l'audit survit sans FK).

## Licence

**GNU Affero General Public License v3 (AGPLv3)** — texte complet dans
`LICENSE`. Projet original basé sur les idées de **Eftivali Gomez**.

Conséquences concrètes : le code est libre d'usage, de modification et de
redistribution, mais **tout dérivé doit rester open source** — y compris
toute exploitation en SaaS/réseau (clause spécifique de l'AGPL). Impossible
de reprendre ce code pour en faire un produit commercial fermé.
Attribution d'origine à conserver.

## Screenshots

<img width="432" height="847" alt="image-1" src="https://github.com/user-attachments/assets/3e6da255-f37c-4094-b992-363da35e09bd" />  <img width="432" height="848" alt="image-2" src="https://github.com/user-attachments/assets/d9fec307-7cac-451c-afe4-f3a4d5c8a708" />

<img width="433" height="851" alt="image-3" src="https://github.com/user-attachments/assets/9b41cb4c-ce8c-42fa-b597-96a901ab77d9" />  <img width="429" height="848" alt="image-4" src="https://github.com/user-attachments/assets/7b786b68-d595-4ace-b5b5-dd152a21fdf9" />

<img width="431" height="848" alt="image-5" src="https://github.com/user-attachments/assets/51c30393-ebd5-47bd-baef-83d7b26f8b76" />  <img width="431" height="844" alt="image-6" src="https://github.com/user-attachments/assets/89899bc5-464f-49eb-b2a6-3970d7ac8e61" />

<img width="423" height="844" alt="image-7" src="https://github.com/user-attachments/assets/6581b353-f3ea-4168-8acb-8e09ebea9974" />  <img width="423" height="844" alt="image-8" src="https://github.com/user-attachments/assets/ea50e98d-a980-4ef2-9d0f-c73704f4bb69" />

<img width="429" height="847" alt="image-9" src="https://github.com/user-attachments/assets/4c5f8b63-e6c7-48ae-9531-ce6e90fc6ef3" />  <img width="429" height="846" alt="image-10" src="https://github.com/user-attachments/assets/a305c902-3aaa-464e-9fcb-0224a7531765" />

<img width="431" height="849" alt="image-11" src="https://github.com/user-attachments/assets/01d2f736-836e-40da-b6bf-653c2ef30565" />











