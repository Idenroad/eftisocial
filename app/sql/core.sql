-- EftiSocial — schéma global "core"
-- Contient : sessions (résidences), superadmins, admins, OTP, jetons,
-- journal d'audit immuable, catalogue d'intérêts.
-- Idempotent : peut être rejoué sans danger.

CREATE SCHEMA IF NOT EXISTS core;

-- ─── Sessions de résidence ────────────────────────────────────────────────────
-- Chaque session possède son propre schéma PostgreSQL (sess_<slug>) : étanchéité
-- totale entre résidences au niveau base de données.
CREATE TABLE IF NOT EXISTS core.sessions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text NOT NULL UNIQUE
                CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,40}$'),
    name        text NOT NULL,
    schema_name text NOT NULL UNIQUE
                CHECK (schema_name ~ '^sess_[a-z0-9_]+$'),
    active      boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ─── Superadmins (accès global) ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS core.superadmins (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email      citext NOT NULL UNIQUE,
    first_name text NOT NULL,
    last_name  text NOT NULL DEFAULT '',
    demo_otp   text,                          -- NULL en production
    active     boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ─── Admins (intervenants) rattachés à UNE session ────────────────────────────
CREATE TABLE IF NOT EXISTS core.admins (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES core.sessions(id) ON DELETE CASCADE,
    email      citext NOT NULL,
    first_name text NOT NULL,
    demo_otp   text,                          -- NULL en production
    active     boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, email)
);

-- ─── Codes OTP ────────────────────────────────────────────────────────────────
-- session_id NULL => OTP de superadmin, sinon OTP d'un membre/admin de session.
CREATE TABLE IF NOT EXISTS core.otp_codes (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email      citext NOT NULL,
    session_id uuid REFERENCES core.sessions(id) ON DELETE CASCADE,
    role       text NOT NULL CHECK (role IN ('superadmin','admin','user')),
    code_hash  text NOT NULL,
    expires_at timestamptz NOT NULL,
    attempts   int NOT NULL DEFAULT 0,
    used       boolean NOT NULL DEFAULT false,
    ip         inet,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS otp_codes_email_idx ON core.otp_codes (email, session_id, created_at);

-- ─── Jetons de session (cookies) ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS core.auth_tokens (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash text NOT NULL UNIQUE,
    role       text NOT NULL CHECK (role IN ('superadmin','admin','user')),
    session_id uuid REFERENCES core.sessions(id) ON DELETE CASCADE,
    actor_id   uuid NOT NULL,               -- id superadmin / admin / user
    remember   boolean NOT NULL DEFAULT false,
    expires_at timestamptz NOT NULL,
    revoked    boolean NOT NULL DEFAULT false,
    ip         inet,
    ua         text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_tokens_hash_idx ON core.auth_tokens (token_hash);
CREATE INDEX IF NOT EXISTS auth_tokens_actor_idx ON core.auth_tokens (role, actor_id);

-- ─── Journal d'audit IMMUABLE ─────────────────────────────────────────────────
-- Toute manipulation de compte/session/événement y est consignée.
-- Le trigger ci-dessous rend UPDATE/DELETE/TRUNCATE impossibles.
-- NB : session_id n'est PAS une FK — une FK ON DELETE SET NULL déclencherait
-- un UPDATE sur audit_log, interdit par le trigger d'immuabilité.
CREATE TABLE IF NOT EXISTS core.audit_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    session_id  uuid,
    actor_role  text NOT NULL,              -- superadmin|admin|user|system
    actor_id    uuid,
    actor_label text,
    action      text NOT NULL,              -- ex: user.create, session.delete…
    target_type text,
    target_id   text,
    details     jsonb NOT NULL DEFAULT '{}'::jsonb,
    ip          inet
);
CREATE INDEX IF NOT EXISTS audit_session_idx ON core.audit_log (session_id, ts);
CREATE INDEX IF NOT EXISTS audit_action_idx  ON core.audit_log (action, ts);

CREATE OR REPLACE FUNCTION core.audit_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log est immuable: % interdit', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS audit_no_update ON core.audit_log;
CREATE TRIGGER audit_no_update
BEFORE UPDATE OR DELETE OR TRUNCATE ON core.audit_log
FOR EACH STATEMENT EXECUTE FUNCTION core.audit_immutable();

-- ─── Catalogue d'intérêts suggérés ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS core.interests (
    name  text PRIMARY KEY,   -- forme normalisée (minuscules, sans accents)
    label text NOT NULL       -- forme affichée
);
