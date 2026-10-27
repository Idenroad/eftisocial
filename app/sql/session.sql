-- EftiSocial — DDL d'un schéma de session (résidence)
-- Appliqué dans le schéma sess_<slug> lors du provisionnement.
-- {schema} est substitué par Python après validation stricte du nom.
-- Idempotent (IF NOT EXISTS partout).

-- ─── Utilisateurs (résidents) ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS {schema}.users (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email      citext NOT NULL UNIQUE,
    first_name text NOT NULL,
    sex        text NOT NULL CHECK (sex IN ('F','M','X')),
    bio        text NOT NULL DEFAULT '',
    demo_otp   text,                          -- NULL en production
    paused     boolean NOT NULL DEFAULT false,
    created_by text NOT NULL DEFAULT 'self'   -- self|admin|import
               CHECK (created_by IN ('self','admin','import')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz                    -- suppression logique
);
CREATE INDEX IF NOT EXISTS users_active_idx ON {schema}.users (id)
    WHERE deleted_at IS NULL;

-- ─── Intérêts d'un utilisateur (max 10, appliqué côté code) ───────────────────
CREATE TABLE IF NOT EXISTS {schema}.user_interests (
    user_id  uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE CASCADE,
    interest text NOT NULL,
    PRIMARY KEY (user_id, interest)
);
CREATE INDEX IF NOT EXISTS ui_interest_idx ON {schema}.user_interests (interest);

-- ─── Photos de profil ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS {schema}.photos (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE CASCADE,
    filename   text NOT NULL,
    is_primary boolean NOT NULL DEFAULT false,
    position   int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS photos_user_idx ON {schema}.photos (user_id);

-- ─── Swipes ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS {schema}.swipes (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    swiper_id  uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE CASCADE,
    target_id  uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE CASCADE,
    action     text NOT NULL CHECK (action IN ('like','pass')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (swiper_id, target_id)
);
CREATE INDEX IF NOT EXISTS swipes_target_idx ON {schema}.swipes (target_id, action);

-- ─── Matchs (paire ordonnée user_a < user_b) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS {schema}.matches (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_a     uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE CASCADE,
    user_b     uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_a, user_b)
);

-- ─── Messages (tchat entre membres matchés) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS {schema}.messages (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id   uuid NOT NULL REFERENCES {schema}.matches(id) ON DELETE CASCADE,
    sender_id  uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE CASCADE,
    body       text NOT NULL CHECK (char_length(body) <= 2000),
    read_at    timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_match_idx ON {schema}.messages (match_id, id);

-- ─── Blocages (invisibilité mutuelle, réversible par le bloqueur) ────────────
CREATE TABLE IF NOT EXISTS {schema}.blocks (
    blocker_id uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE CASCADE,
    blocked_id uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (blocker_id, blocked_id)
);
CREATE INDEX IF NOT EXISTS blocks_blocked_idx ON {schema}.blocks (blocked_id);

-- ─── Signalements (comportement signalé aux intervenants) ────────────────────
CREATE TABLE IF NOT EXISTS {schema}.reports (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    reporter_id uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE CASCADE,
    reported_id uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE CASCADE,
    reason      text NOT NULL CHECK (reason IN ('comportement','spam','photo','autre')),
    details     text NOT NULL DEFAULT '',
    handled     boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reports_open_idx ON {schema}.reports (handled, created_at);

-- ─── Catalogue de passions de la résidence (créé par l'intervenant) ──────────
CREATE TABLE IF NOT EXISTS {schema}.session_interests (
    name       text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ─── Passions interdites (mot normalisé refusé à l'enregistrement) ────────────
CREATE TABLE IF NOT EXISTS {schema}.banned_interests (
    name       text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ─── Événements ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS {schema}.events (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title            text NOT NULL,
    description      text NOT NULL DEFAULT '',
    location         text NOT NULL DEFAULT '',
    event_at         timestamptz NOT NULL,
    max_participants int CHECK (max_participants IS NULL OR max_participants > 0),
    creator_role     text NOT NULL CHECK (creator_role IN ('superadmin','admin','user')),
    creator_id       uuid,
    creator_name     text NOT NULL DEFAULT '',
    cancelled        boolean NOT NULL DEFAULT false,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_date_idx ON {schema}.events (event_at);

-- ─── Participations aux événements ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS {schema}.event_participants (
    event_id   uuid NOT NULL REFERENCES {schema}.events(id) ON DELETE CASCADE,
    user_id    uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, user_id)
);
