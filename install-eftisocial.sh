#!/usr/bin/env bash
#
# install-eftisocial.sh — Installer EftiSocial sur Debian 13 Trixie (LXC)
#
# Étapes :
#   1. Dépendances système (python3-venv, postgresql…)
#   2. Copie du projet dans /opt/eftisocial + venv + pip
#   3. PostgreSQL : rôle + base randomisés, extensions
#   4. Config superadmin (email + prénom + nom)
#   5. Config SMTP (optionnelle — requis en production pour les OTP)
#   6. .env généré (SECRET_KEY, DATABASE_URL, SMTP, DATA_DIR)
#   7. initdb + superadmin (+ données démo si demandé)
#   8. Service systemd gunicorn
#   9. eftisocial_credentials.txt avec tous les identifiants
#
# Usage :
#   sudo bash install-eftisocial.sh [chemin/vers/eftisocial-src]
#
set -euo pipefail

# ─── Couleurs ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ─── Préliminaires ───────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "Ce script doit être exécuté en root : sudo bash install-eftisocial.sh"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${1:-$SCRIPT_DIR}"
INSTALL_DIR="/opt/eftisocial"
DATA_DIR="/var/lib/eftisocial"
CRED_FILE="${SCRIPT_DIR}/eftisocial_credentials.txt"

if [[ ! -f "${SRC_DIR}/wsgi.py" ]] || [[ ! -f "${SRC_DIR}/requirements.txt" ]]; then
    error "Sources introuvables dans ${SRC_DIR} (wsgi.py / requirements.txt manquants)."
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       EftiSocial — Installer (Debian 13 Trixie / LXC)         ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ─── 1. Dépendances système ──────────────────────────────────────────────────
info "Étape 1/9 — Dépendances système"

export DEBIAN_FRONTEND=noninteractive

if ! command -v apt-get &>/dev/null; then
    error "apt-get non trouvé. Ce script nécessite Debian."
fi

apt-get update -qq
apt-get install -y -qq \
    ca-certificates \
    python3 \
    python3-venv \
    python3-pip \
    libpq-dev \
    postgresql \
    postgresql-contrib \
    locales \
    2>&1 | tail -3

ok "Paquets installés"

# Locales UTF-8 (LXC bare n'a aucune locale)
info "Configuration des locales UTF-8..."
_locale_gen_entry() {
    sed -i "s/^# *$1 UTF-8/$1 UTF-8/" /etc/locale.gen 2>/dev/null \
        || echo "$1 UTF-8" >> /etc/locale.gen
}
for loc in fr_CA.UTF-8 fr_FR.UTF-8 en_US.UTF-8 en_CA.UTF-8; do
    _locale_gen_entry "$loc"
done
locale-gen 2>&1 | tail -2 || true

_locale_exists() {
    local want
    want="$(echo "${1,,}" | tr -d '-')"
    locale -a 2>/dev/null | tr 'A-Z' 'a-z' | tr -d '-' | grep -qxF "$want"
}

SYS_LOCALE="C.UTF-8"
for loc in fr_CA.UTF-8 fr_FR.UTF-8 en_CA.UTF-8 en_US.UTF-8; do
    if _locale_exists "$loc"; then SYS_LOCALE="$loc"; break; fi
done
update-locale LANG="$SYS_LOCALE" LC_ALL="$SYS_LOCALE" 2>/dev/null || true
export LANG="$SYS_LOCALE" LC_ALL="$SYS_LOCALE" PYTHONIOENCODING=utf-8

DB_LOCALE="C.UTF-8"
for loc in fr_CA.UTF-8 en_CA.UTF-8 en_US.UTF-8; do
    if _locale_exists "$loc"; then DB_LOCALE="$loc"; break; fi
done
ok "Locales : système=${SYS_LOCALE}, PostgreSQL=${DB_LOCALE}"

# ─── 2. Copie du projet + venv ───────────────────────────────────────────────
info "Étape 2/9 — Installation du code dans ${INSTALL_DIR}"

mkdir -p "$INSTALL_DIR" "$DATA_DIR"
if [[ "$(realpath "$SRC_DIR")" == "$(realpath "$INSTALL_DIR")" ]]; then
    info "Sources déjà dans ${INSTALL_DIR} — copie ignorée"
elif command -v rsync &>/dev/null; then
    rsync -a --delete \
        --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
        --exclude='data' --exclude='.env' --exclude='tests' \
        --exclude='.venv' --exclude='.pytest_cache' \
        "${SRC_DIR}/" "$INSTALL_DIR/"
else
    # Fallback sans rsync
    cp -r "${SRC_DIR}/." "$INSTALL_DIR/"
    rm -rf "$INSTALL_DIR/data" "$INSTALL_DIR/tests" "$INSTALL_DIR/.venv" \
           "$INSTALL_DIR/.git" "$INSTALL_DIR/.pytest_cache"
    find "$INSTALL_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    rm -f "$INSTALL_DIR/.env"
fi

cd "$INSTALL_DIR"
if [[ ! -x "${INSTALL_DIR}/.venv/bin/python3" ]]; then
    python3 -m venv "${INSTALL_DIR}/.venv"
fi
"${INSTALL_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install --quiet -r requirements.txt
ok "Venv prêt : $(${INSTALL_DIR}/.venv/bin/python3 --version)"

# ─── 3. PostgreSQL ───────────────────────────────────────────────────────────
info "Étape 3/9 — Configuration de PostgreSQL"

systemctl start postgresql 2>/dev/null || service postgresql start
systemctl enable postgresql 2>/dev/null || true

DB_SUFFIX=$(head -c 8 /dev/urandom | base64 | tr -dc 'a-z0-9' | head -c 8)
DB_NAME="eftisocial_${DB_SUFFIX}"
DB_USER="eftisocial_${DB_SUFFIX}"
DB_PASSWORD=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 24)

PG_VERNUM=$(sudo -u postgres psql -Atqc "SHOW server_version_num" 2>/dev/null || echo 0)
LOCALE_PROVIDER_CLAUSE=""
if [ "${PG_VERNUM:-0}" -ge 150000 ]; then
    LOCALE_PROVIDER_CLAUSE="LOCALE_PROVIDER libc"
fi

sudo -u postgres psql -v ON_ERROR_STOP=1 <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
    ELSE
        ALTER ROLE ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';
    END IF;
END
\$\$;

SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER} ENCODING ''UTF8''
        LC_COLLATE ''${DB_LOCALE}'' LC_CTYPE ''${DB_LOCALE}''
        TEMPLATE template0 ${LOCALE_PROVIDER_CLAUSE}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\gexec

GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
EOF

# DB de test séparée (pytest)
DB_TEST_NAME="eftisocial_test_${DB_SUFFIX}"
DB_TEST_USER="eftisocial_test_${DB_SUFFIX}"
DB_TEST_PASSWORD=$(head -c 16 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 16)

sudo -u postgres psql -v ON_ERROR_STOP=1 <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_TEST_USER}') THEN
        CREATE ROLE ${DB_TEST_USER} LOGIN PASSWORD '${DB_TEST_PASSWORD}' NOSUPERUSER;
    END IF;
END
\$\$;

SELECT 'CREATE DATABASE ${DB_TEST_NAME} OWNER ${DB_TEST_USER} ENCODING ''UTF8''
        LC_COLLATE ''${DB_LOCALE}'' LC_CTYPE ''${DB_LOCALE}''
        TEMPLATE template0 ${LOCALE_PROVIDER_CLAUSE}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_TEST_NAME}')\gexec

REVOKE CONNECT ON DATABASE ${DB_NAME} FROM PUBLIC;
GRANT CONNECT ON DATABASE ${DB_NAME} TO ${DB_USER};
EOF

ok "PostgreSQL : ${DB_USER}@${DB_NAME} (+ ${DB_TEST_USER}@${DB_TEST_NAME})"

# ─── 4. Compte superadmin ────────────────────────────────────────────────────
info "Étape 4/9 — Compte superadmin"
echo ""
echo -e "${BOLD}Compte superadmin${NC} (accès global, gère sessions + intervenants)"
echo ""

while true; do
    read -rp "   Email du superadmin : " ADMIN_EMAIL
    if [[ "$ADMIN_EMAIL" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
        break
    fi
    warn "Email invalide."
done
read -rp "   Prénom (défaut : Super) : " ADMIN_FIRST
ADMIN_FIRST="${ADMIN_FIRST:-Super}"
read -rp "   Nom (défaut : Admin) : " ADMIN_LAST
ADMIN_LAST="${ADMIN_LAST:-Admin}"
ok "Superadmin : ${ADMIN_EMAIL}"

# ─── 5. SMTP ─────────────────────────────────────────────────────────────────
info "Étape 5/9 — Configuration SMTP (OTP par courriel)"
echo ""
echo -e "${BOLD}SMTP${NC} — nécessaire en production pour envoyer les codes OTP."
echo "   Laisser vide = les codes sont écrits dans les logs (dév/démo seulement)."
echo ""

read -rp "   Serveur SMTP (ex. smtp.gmail.com, vide pour skip) : " MAIL_SERVER
MAIL_PORT="" ; MAIL_USE_TLS="True" ; MAIL_USE_SSL="False"
MAIL_USERNAME="" ; MAIL_PASSWORD="" ; MAIL_DEFAULT_SENDER=""

if [[ -n "$MAIL_SERVER" ]]; then
    read -rp "   Port (587=STARTTLS, 465=SSL, défaut 587) : " MAIL_PORT
    MAIL_PORT="${MAIL_PORT:-587}"
    if [[ "$MAIL_PORT" == "465" ]]; then
        MAIL_USE_SSL="True" ; MAIL_USE_TLS="False"
    fi
    read -rp "   Login SMTP : " MAIL_USERNAME
    read -rp "   Mot de passe SMTP : " MAIL_PASSWORD
    MAIL_DEFAULT_SENDER="${MAIL_USERNAME}"
    ok "SMTP : ${MAIL_SERVER}:${MAIL_PORT}"
else
    warn "SMTP désactivé — les OTP seront dans les logs gunicorn."
fi

# ─── 5b. Mode démo ? ────────────────────────────────────────────────────────
echo ""
read -rp "   Installer les données de DÉMO (3 membres + intervenant, OTP fixes) ? (o/N) : " DEMO_ANSWER
DEMO_MODE="False"
if [[ "${DEMO_ANSWER,,}" == "o" || "${DEMO_ANSWER,,}" == "oui" || "${DEMO_ANSWER,,}" == "y" ]]; then
    DEMO_MODE="True"
fi

# ─── 6. .env ─────────────────────────────────────────────────────────────────
info "Étape 6/9 — Génération du .env"

SECRET_KEY=$(head -c 48 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 64)

read -rp "   L'app est-elle derrière un reverse proxy HTTPS ? (o/N) : " PROXY_ANSWER
TRUST_PROXY="false" ; SESSION_COOKIE_SECURE="False" ; PUBLIC_URL=""
if [[ "${PROXY_ANSWER,,}" == "o" || "${PROXY_ANSWER,,}" == "y" ]]; then
    TRUST_PROXY="true" ; SESSION_COOKIE_SECURE="True"
    read -rp "   URL publique (ex. https://eftisocial.exemple.com) : " PUBLIC_URL
    PUBLIC_URL="${PUBLIC_URL%%/}"
fi

cat > "${INSTALL_DIR}/.env" <<EOF
# EftiSocial — généré par install-eftisocial.sh le $(date '+%Y-%m-%d %H:%M:%S')
SECRET_KEY=${SECRET_KEY}

DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
DATABASE_URL_TEST=postgresql://${DB_TEST_USER}:${DB_TEST_PASSWORD}@localhost:5432/${DB_TEST_NAME}

DATA_DIR=${DATA_DIR}

MAIL_SERVER=${MAIL_SERVER}
MAIL_PORT=${MAIL_PORT:-587}
MAIL_USE_TLS=${MAIL_USE_TLS}
MAIL_USE_SSL=${MAIL_USE_SSL}
MAIL_USERNAME=${MAIL_USERNAME}
MAIL_PASSWORD=${MAIL_PASSWORD}
MAIL_DEFAULT_SENDER=${MAIL_DEFAULT_SENDER}

DEMO_MODE=${DEMO_MODE}
SESSION_COOKIE_SECURE=${SESSION_COOKIE_SECURE}
TRUST_PROXY=${TRUST_PROXY}
PUBLIC_URL=${PUBLIC_URL}
EOF
chmod 600 "${INSTALL_DIR}/.env"
ln -sf "${INSTALL_DIR}/.env" "${DATA_DIR}/.env"
ok ".env écrit"

# ─── 7. Init DB + superadmin (+ démo) ────────────────────────────────────────
info "Étape 7/9 — Initialisation de la base"

cd "$INSTALL_DIR"
export DATA_DIR

"${INSTALL_DIR}/.venv/bin/python" cli.py initdb
"${INSTALL_DIR}/.venv/bin/python" cli.py create-superadmin "$ADMIN_EMAIL" \
    --first-name "$ADMIN_FIRST" --last-name "$ADMIN_LAST"

if [[ "$DEMO_MODE" == "True" ]]; then
    "${INSTALL_DIR}/.venv/bin/python" cli.py seed-demo
fi

# ─── Utilisateur système ─────────────────────────────────────────────────────
if ! id -u eftisocial &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin \
        --home-dir "$INSTALL_DIR" eftisocial
fi
chown -R eftisocial:eftisocial "$INSTALL_DIR" "$DATA_DIR"

# ─── 8. Service systemd ──────────────────────────────────────────────────────
info "Étape 8/9 — Service systemd"

read -rp "   Port d'écoute (défaut 5000) : " EFTI_PORT
EFTI_PORT="${EFTI_PORT:-5000}"
read -rp "   Host d'écoute (défaut 127.0.0.1, 0.0.0.0 pour public) : " EFTI_HOST
EFTI_HOST="${EFTI_HOST:-127.0.0.1}"

cat > /etc/systemd/system/eftisocial.service <<UNIT
[Unit]
Description=EftiSocial — rencontres en résidences pour aînés
After=network.target postgresql.service
Requires=postgresql.service
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=eftisocial
Group=eftisocial
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
Environment=PATH=${INSTALL_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
Environment=LANG=${SYS_LOCALE}
Environment=LC_ALL=${SYS_LOCALE}
ExecStart=${INSTALL_DIR}/.venv/bin/gunicorn \
    --workers 3 --threads 4 \
    --bind ${EFTI_HOST}:${EFTI_PORT} \
    --access-logfile - --error-logfile - \
    'wsgi:app'
ExecStartPre=-/usr/bin/pkill -f "wsgi:app"
Restart=always
RestartSec=5
TimeoutStopSec=30
KillMode=control-group

# Sécurité
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${DATA_DIR} ${INSTALL_DIR}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable eftisocial
systemctl restart eftisocial || warn "Démarrage échoué — voir journalctl -u eftisocial"

sleep 2
if systemctl is-active --quiet eftisocial; then
    ok "Service actif sur ${EFTI_HOST}:${EFTI_PORT}"
    SYSTEMD_OK=true
else
    warn "Le service ne répond pas — journalctl -u eftisocial -f"
    SYSTEMD_OK=false
fi

# ─── 9. Credentials ──────────────────────────────────────────────────────────
info "Étape 9/9 — Fichier d'identifiants"

cat > "$CRED_FILE" <<EOF
╔══════════════════════════════════════════════════════════════════════╗
║         EFTISOCIAL — INFORMATIONS D'INSTALLATION                     ║
║         Généré le $(date '+%Y-%m-%d %H:%M:%S')                       ║
╚══════════════════════════════════════════════════════════════════════╝

⚠️  SÉCURITÉ — LISEZ CECI ⚠️
Ce fichier contient des identifiants en clair.
1. Copiez-les dans un gestionnaire de mots de passe.
2. Supprimez ce fichier : sudo rm ${CRED_FILE}

════════════════════════════════════════════════════════════════════════
 APPLICATION
════════════════════════════════════════════════════════════════════════

  Répertoire d'installation : ${INSTALL_DIR}
  Répertoire de données      : ${DATA_DIR}
  Fichier .env               : ${INSTALL_DIR}/.env
  Python                     : $(${INSTALL_DIR}/.venv/bin/python3 --version 2>&1)
  Écoute                     : http://${EFTI_HOST}:${EFTI_PORT}

  Commandes :
    sudo systemctl status eftisocial
    sudo systemctl restart eftisocial
    sudo journalctl -u eftisocial -f        (logs temps réel)
    cd ${INSTALL_DIR} && .venv/bin/python cli.py --help

════════════════════════════════════════════════════════════════════════
 COMPTE SUPERADMIN
════════════════════════════════════════════════════════════════════════

  Email     : ${ADMIN_EMAIL}
  Prénom    : ${ADMIN_FIRST}
  Nom       : ${ADMIN_LAST}
  Connexion : http://${EFTI_HOST}:${EFTI_PORT}/superadmin/connexion
              (code OTP envoyé par courriel — ou dans les logs si pas de SMTP)

════════════════════════════════════════════════════════════════════════
 BASE DE DONNÉES
════════════════════════════════════════════════════════════════════════

  Host       : localhost
  Port       : 5432
  Database   : ${DB_NAME}
  User       : ${DB_USER}
  Password   : ${DB_PASSWORD}
  URL        : postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}

  DB de test : ${DB_TEST_NAME} (user ${DB_TEST_USER} / ${DB_TEST_PASSWORD})

  Connexion : PGPASSWORD='${DB_PASSWORD}' psql -U ${DB_USER} -d ${DB_NAME} -h localhost

════════════════════════════════════════════════════════════════════════
 SMTP
════════════════════════════════════════════════════════════════════════

  Serveur   : ${MAIL_SERVER:-<non configuré>}
  Port      : ${MAIL_PORT:-<non configuré>}
  Login     : ${MAIL_USERNAME:-<non configuré>}

  ⚠️  Sans SMTP, les OTP de connexion sont écrits dans les logs
     (journalctl -u eftisocial). Configurez SMTP dans .env pour la prod.

════════════════════════════════════════════════════════════════════════
 CLÉ SECRÈTE
════════════════════════════════════════════════════════════════════════

  SECRET_KEY : ${SECRET_KEY}
  ⚠️  Ne la perdez pas — toutes les sessions seraient invalidées.

════════════════════════════════════════════════════════════════════════
 SERVICE SYSTEMD
════════════════════════════════════════════════════════════════════════
EOF

if [[ "$SYSTEMD_OK" == true ]]; then
cat >> "$CRED_FILE" <<EOF
  Service : eftisocial.service (ACTIF)
  Host:Port : ${EFTI_HOST}:${EFTI_PORT}
EOF
else
cat >> "$CRED_FILE" <<EOF
  Service : eftisocial.service (NON ACTIF — vérifier journalctl)
EOF
fi

if [[ "$DEMO_MODE" == "True" ]]; then
cat >> "$CRED_FILE" <<EOF

════════════════════════════════════════════════════════════════════════
 DONNÉES DÉMO (installées — supprimez-les en production !)
════════════════════════════════════════════════════════════════════════

  Session : /residence-demo

  Membres (connexion /residence-demo/connexion) :
    JC    : jc@demo.local        OTP : 111111
    Alex  : alex@demo.local      OTP : 222222
    Lugus : lugus@demo.local     OTP : 333333

  Intervenant (connexion /residence-demo/admin/connexion) :
    intervenant@demo.local       OTP : 444

  ⚠️  Ces codes OTP sont STATIQUES — à n'utiliser qu'en démo.
EOF
fi

cat >> "$CRED_FILE" <<EOF

════════════════════════════════════════════════════════════════════════
 ACTIONS REQUISES APRÈS INSTALLATION
════════════════════════════════════════════════════════════════════════

  1. Copiez ces informations dans un gestionnaire de mots de passe.
  2. Supprimez ce fichier : sudo rm ${CRED_FILE}
  3. Configurez un reverse proxy HTTPS (nginx, Caddy…)
  4. Testez : http://${EFTI_HOST}:${EFTI_PORT}/

════════════════════════════════════════════════════════════════════════
EOF

chmod 600 "$CRED_FILE"
chown root:root "$CRED_FILE"
ok "Fichier d'identifiants : ${CRED_FILE}"

# ─── Résumé ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║  EFTISOCIAL INSTALLÉ AVEC SUCCÈS                             ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Application :${NC}  ${INSTALL_DIR}"
echo -e "  ${BOLD}Écoute :${NC}       http://${EFTI_HOST}:${EFTI_PORT}"
echo -e "  ${BOLD}Superadmin :${NC}   ${ADMIN_EMAIL}"
echo -e "  ${BOLD}Identifiants :${NC} ${CRED_FILE}"
if [[ "$DEMO_MODE" == "True" ]]; then
echo -e "  ${BOLD}Démo :${NC}         http://${EFTI_HOST}:${EFTI_PORT}/residence-demo"
fi
echo ""
echo -e "  ${YELLOW}⚠️  Lisez ${CRED_FILE} puis supprimez-le.${NC}"
echo ""
