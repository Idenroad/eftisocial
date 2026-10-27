"""Logique de matching et de découverte.

Algorithme « Trouver » : classement par nombre d'intérêts communs décroissant,
puis par ancienneté. Exclus : soi-même, comptes en pause/supprimés, déjà swipés.
Un « like » réciproque crée un match (paire ordonnée, unique).
"""

import re

from .db import sess_conn, normalize_interest


def _user_public_fields(schema: str, cur, user_id, include_paused=False):
    sql = ("SELECT id, first_name, sex, bio, paused, created_by FROM users "
           "WHERE id = %s AND deleted_at IS NULL")
    if not include_paused:
        sql += " AND paused = false"
    cur.execute(sql, (str(user_id),))
    return cur.fetchone()


def user_interests(cur, user_id) -> list[str]:
    cur.execute(
        "SELECT interest FROM user_interests WHERE user_id = %s ORDER BY interest",
        (str(user_id),))
    return [r["interest"] for r in cur.fetchall()]


def user_interests_for(schema: str, user_id) -> list[str]:
    """Intérêts normalisés d'un membre."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            return user_interests(cur, user_id)


def get_profile(schema: str, user_id, include_paused: bool = False,
                viewer_id=None) -> dict | None:
    """Profil public d'un membre. `viewer_id` : exclut si blocage mutuel."""
    if viewer_id and is_blocked(schema, viewer_id, user_id):
        return None
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            u = _user_public_fields(schema, cur, user_id, include_paused)
            if not u:
                return None
            cur.execute(
                "SELECT id, filename, is_primary FROM photos WHERE user_id = %s "
                "ORDER BY is_primary DESC, position, created_at",
                (str(user_id),))
            u["photos"] = [dict(r) for r in cur.fetchall()]
            u["interests"] = user_interests(cur, user_id)
    return u


def next_deck(schema: str, user_id, limit: int = 10) -> list[dict]:
    """Pile de profils à swiper, triée par intérêts communs décroissants."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.first_name, u.sex, u.bio,
                       (SELECT filename FROM photos p
                         WHERE p.user_id = u.id
                         ORDER BY p.is_primary DESC, p.position LIMIT 1
                       ) AS photo,
                       (SELECT count(*) FROM user_interests a
                         JOIN user_interests b
                           ON a.interest = b.interest AND b.user_id = %s
                         WHERE a.user_id = u.id) AS shared
                FROM users u
                WHERE u.deleted_at IS NULL
                  AND u.paused = false
                  AND u.id <> %s
                  AND NOT EXISTS (
                        SELECT 1 FROM swipes s
                        WHERE s.swiper_id = %s AND s.target_id = u.id)
                  AND NOT EXISTS (
                        SELECT 1 FROM blocks bl
                        WHERE (bl.blocker_id = %s AND bl.blocked_id = u.id)
                           OR (bl.blocker_id = u.id AND bl.blocked_id = %s))
                ORDER BY shared DESC, u.created_at
                LIMIT %s
                """,
                (str(user_id), str(user_id), str(user_id),
                 str(user_id), str(user_id), limit),
            )
            cards = []
            for r in cur.fetchall():
                cur.execute(
                    "SELECT a.interest FROM user_interests a "
                    "JOIN user_interests b ON a.interest = b.interest "
                    "WHERE a.user_id = %s AND b.user_id = %s ORDER BY a.interest",
                    (r["id"], str(user_id)))
                r["shared_interests"] = [i["interest"] for i in cur.fetchall()]
                cards.append(dict(r))
            return cards


def record_swipe(schema: str, swiper_id, target_id, action: str) -> dict:
    """Enregistre un swipe. Retourne {matched: bool, match_id}."""
    if action not in ("like", "pass"):
        raise ValueError("action invalide")
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            # Le compte cible doit exister et être visible
            cur.execute(
                "SELECT 1 FROM users WHERE id = %s AND deleted_at IS NULL "
                "AND paused = false", (str(target_id),))
            if not cur.fetchone():
                return {"matched": False, "match_id": None}

            cur.execute(
                "INSERT INTO swipes (swiper_id, target_id, action) "
                "VALUES (%s,%s,%s) "
                "ON CONFLICT (swiper_id, target_id) DO UPDATE SET action = %s",
                (str(swiper_id), str(target_id), action, action))

            if action != "like":
                return {"matched": False, "match_id": None}

            cur.execute(
                "SELECT 1 FROM swipes WHERE swiper_id = %s AND target_id = %s "
                "AND action = 'like'",
                (str(target_id), str(swiper_id)))
            if not cur.fetchone():
                return {"matched": False, "match_id": None}

            a, b = sorted([str(swiper_id), str(target_id)])
            cur.execute(
                "INSERT INTO matches (user_a, user_b) VALUES (%s,%s) "
                "ON CONFLICT (user_a, user_b) DO NOTHING RETURNING id",
                (a, b))
            row = cur.fetchone()
            return {"matched": True, "match_id": row and str(row["id"])}


# ─── Tchat (messages entre matchs) ────────────────────────────────────────────

def get_match(schema: str, match_id, user_id) -> dict | None:
    """Match dont `user_id` fait partie (+ infos de l'autre membre)."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id AS match_id, m.created_at,
                       u.id, u.first_name, u.sex,
                       (SELECT filename FROM photos p
                         WHERE p.user_id = u.id
                         ORDER BY p.is_primary DESC, p.position LIMIT 1
                       ) AS photo
                FROM matches m
                JOIN users u ON u.id = CASE WHEN m.user_a = %s
                                            THEN m.user_b ELSE m.user_a END
                WHERE m.id = %s AND (m.user_a = %s OR m.user_b = %s)
                  AND u.deleted_at IS NULL
                """,
                (str(user_id), str(match_id), str(user_id), str(user_id)))
            row = cur.fetchone()
    return dict(row) if row else None


def list_messages(schema: str, match_id, user_id, after_id: int = 0) -> list[dict]:
    """Messages d'un match (vérifie que l'usager en fait partie)."""
    if not get_match(schema, match_id, user_id):
        return []
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, sender_id, body, created_at "
                "FROM messages WHERE match_id = %s AND id > %s "
                "ORDER BY id LIMIT 200",
                (str(match_id), after_id))
            return [dict(r) for r in cur.fetchall()]


def send_message(schema: str, match_id, sender_id, body: str) -> dict | None:
    """Envoie un message. None si l'usager n'est pas dans le match."""
    body = (body or "").strip()
    if not body or len(body) > 2000:
        return None
    if not get_match(schema, match_id, sender_id):
        return None
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (match_id, sender_id, body) "
                "VALUES (%s,%s,%s) RETURNING id, sender_id, body, created_at",
                (str(match_id), str(sender_id), body))
            return dict(cur.fetchone())


def unread_counts(schema: str, user_id) -> dict:
    """Nb de messages non lus par match (pour badge « Matchs »)."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id AS match_id, count(msg.id) AS unread
                FROM matches m
                JOIN messages msg ON msg.match_id = m.id
                 AND msg.sender_id <> %s AND msg.read_at IS NULL
                WHERE m.user_a = %s OR m.user_b = %s
                GROUP BY m.id
                """,
                (str(user_id), str(user_id), str(user_id)))
            return {str(r["match_id"]): r["unread"]
                    for r in cur.fetchall()}


def mark_read(schema: str, match_id, reader_id) -> None:
    """Marque lus les messages reçus dans un match."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE messages SET read_at = now() "
                "WHERE match_id = %s AND sender_id <> %s AND read_at IS NULL",
                (str(match_id), str(reader_id)))


def delete_match(schema: str, match_id, user_id) -> bool:
    """Supprime un match ET les likes mutuels : les deux profils
    retournent dans le pool de swipe (contrairement à Tinder)."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM matches WHERE id = %s "
                "AND (user_a = %s OR user_b = %s) "
                "RETURNING user_a, user_b",
                (str(match_id), str(user_id), str(user_id)))
            row = cur.fetchone()
            if not row:
                return False
            a, b = str(row["user_a"]), str(row["user_b"])
            cur.execute(
                "DELETE FROM swipes "
                "WHERE (swiper_id = %s AND target_id = %s) "
                "   OR (swiper_id = %s AND target_id = %s)",
                (a, b, b, a))
            return True


def is_blocked(schema: str, viewer_id, target_id) -> bool:
    """Blocage dans UN sens ou l'autre (invisibilité mutuelle)."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM blocks "
                "WHERE (blocker_id = %s AND blocked_id = %s) "
                "   OR (blocker_id = %s AND blocked_id = %s)",
                (str(viewer_id), str(target_id),
                 str(target_id), str(viewer_id)))
            return cur.fetchone() is not None


def block_user(schema: str, blocker_id, blocked_id) -> None:
    """Bloque : supprime match + swipes (un blocage coupe le lien),
    puis enregistre le blocage."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            a, b = str(blocker_id), str(blocked_id)
            cur.execute(
                "DELETE FROM matches "
                "WHERE (user_a = %s AND user_b = %s) "
                "   OR (user_a = %s AND user_b = %s)",
                (a, b, b, a))
            cur.execute(
                "DELETE FROM swipes "
                "WHERE (swiper_id = %s AND target_id = %s) "
                "   OR (swiper_id = %s AND target_id = %s)",
                (a, b, b, a))
            cur.execute(
                "INSERT INTO blocks (blocker_id, blocked_id) "
                "VALUES (%s,%s) ON CONFLICT DO NOTHING", (a, b))


def unblock_user(schema: str, blocker_id, blocked_id) -> bool:
    """Débloque : les deux profils redeviennent visibles dans le pool."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM blocks WHERE blocker_id = %s AND blocked_id = %s",
                (str(blocker_id), str(blocked_id)))
            return cur.rowcount > 0


def list_blocked(schema: str, blocker_id) -> list[dict]:
    """Membres bloqués par cet usager (page profil, bouton débloquer)."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT b.blocked_id AS id, u.first_name, b.created_at "
                "FROM blocks b JOIN users u ON u.id = b.blocked_id "
                "WHERE b.blocker_id = %s ORDER BY b.created_at DESC",
                (str(blocker_id),))
            return [dict(r) for r in cur.fetchall()]


def report_user(schema: str, reporter_id, reported_id, reason: str,
                details: str) -> str | None:
    """Signalement d'un membre aux intervenants."""
    if reason not in ("comportement", "spam", "photo", "autre"):
        return None
    details = (details or "").strip()[:500]
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM users WHERE id = %s AND deleted_at IS NULL",
                (str(reported_id),))
            if not cur.fetchone():
                return None
            cur.execute(
                "INSERT INTO reports (reporter_id, reported_id, reason, "
                "details) VALUES (%s,%s,%s,%s) RETURNING id",
                (str(reporter_id), str(reported_id), reason, details))
            return str(cur.fetchone()["id"])


def list_reports(schema: str, open_only: bool = True) -> list[dict]:
    """Signalements pour le panneau intervenant."""
    where = "WHERE r.handled = false" if open_only else ""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT r.*, a.first_name AS reporter_name,
                       b.first_name AS reported_name, b.email AS reported_email
                FROM reports r
                JOIN users a ON a.id = r.reporter_id
                JOIN users b ON b.id = r.reported_id
                {where}
                ORDER BY r.created_at DESC LIMIT 200
                """)
            return [dict(r) for r in cur.fetchall()]


def mark_report_handled(schema: str, report_id) -> bool:
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE reports SET handled = true WHERE id = %s",
                (str(report_id),))
            return cur.rowcount > 0


def list_matches(schema: str, user_id) -> list[dict]:
    """Matchs d'un membre, avec photo et intérêts communs."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id AS match_id, m.created_at,
                       u.id, u.first_name, u.sex,
                       (SELECT filename FROM photos p
                         WHERE p.user_id = u.id
                         ORDER BY p.is_primary DESC, p.position LIMIT 1
                       ) AS photo
                FROM matches m
                JOIN users u ON u.id = CASE WHEN m.user_a = %s
                                            THEN m.user_b ELSE m.user_a END
                WHERE (m.user_a = %s OR m.user_b = %s)
                  AND u.deleted_at IS NULL
                ORDER BY m.created_at DESC
                """,
                (str(user_id), str(user_id), str(user_id)))
            return [dict(r) for r in cur.fetchall()]


# ─── Découverte ───────────────────────────────────────────────────────────────

def interests_overview(schema: str, viewer_id) -> list[dict]:
    """Tous les intérêts de la session avec nb de membres (hors soi)."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ui.interest, count(*) AS members,
                       bool_or(ui.user_id = %s) AS mine
                FROM user_interests ui
                JOIN users u ON u.id = ui.user_id
                WHERE u.deleted_at IS NULL AND u.paused = false
                GROUP BY ui.interest
                ORDER BY members DESC, ui.interest
                """,
                (str(viewer_id),))
            return [dict(r) for r in cur.fetchall()]


def users_by_interest(schema: str, viewer_id, interest: str) -> list[dict]:
    """Membres actifs partageant un intérêt donné."""
    norm = normalize_interest(interest)
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.first_name, u.sex, u.bio,
                       (SELECT filename FROM photos p
                         WHERE p.user_id = u.id
                         ORDER BY p.is_primary DESC, p.position LIMIT 1
                       ) AS photo,
                       (SELECT count(*) FROM user_interests a
                         JOIN user_interests b
                           ON a.interest = b.interest AND b.user_id = %s
                         WHERE a.user_id = u.id) AS shared
                FROM users u
                JOIN user_interests ui ON ui.user_id = u.id AND ui.interest = %s
                WHERE u.deleted_at IS NULL AND u.paused = false AND u.id <> %s
                  AND NOT EXISTS (
                        SELECT 1 FROM blocks bl
                        WHERE (bl.blocker_id = %s AND bl.blocked_id = u.id)
                           OR (bl.blocker_id = u.id AND bl.blocked_id = %s))
                ORDER BY shared DESC, u.first_name
                """,
                (str(viewer_id), norm, str(viewer_id),
                 str(viewer_id), str(viewer_id)))
            return [dict(r) for r in cur.fetchall()]


# ─── Profil / intérêts ────────────────────────────────────────────────────────

def set_user_interests(schema: str, user_id, interests: list[str]) -> list[str]:
    """Remplace la liste d'intérêts (normalisés, max MAX_INTERESTS).
    Les passions interdites par l'intervenant sont ignorées."""
    from flask import current_app, has_app_context
    max_i = (current_app.config["MAX_INTERESTS"] if has_app_context()
             else 10)

    banned = get_banned(schema)

    # Les items peuvent être des chaînes « a, b, c » (champ texte unique)
    # ou des valeurs multiples — on supporte les deux.
    seen, clean = set(), []
    for item in interests:
        for raw in re.split(r"[,;\n]", str(item)):
            n = normalize_interest(raw)
            if n and n not in seen and n not in banned and len(n) <= 60:
                seen.add(n)
                clean.append(n)
    clean = clean[:max_i]

    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_interests WHERE user_id = %s",
                        (str(user_id),))
            for i in clean:
                cur.execute(
                    "INSERT INTO user_interests (user_id, interest) "
                    "VALUES (%s,%s)", (str(user_id), i))
    return clean


# ─── Catalogue et interdictions de passions ──────────────────────────────────

def get_banned(schema: str) -> set[str]:
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM banned_interests")
            return {r["name"] for r in cur.fetchall()}


def list_catalog(schema: str) -> list[str]:
    """Passions suggérées par l'intervenant (aide à la saisie)."""
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM session_interests ORDER BY name")
            return [r["name"] for r in cur.fetchall()]


def add_catalog(schema: str, name: str) -> str | None:
    n = normalize_interest(name)
    if not n or n in get_banned(schema) or len(n) > 60:
        return None
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO session_interests (name) VALUES (%s) "
                "ON CONFLICT DO NOTHING", (n,))
    return n


def remove_catalog(schema: str, name: str) -> None:
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM session_interests WHERE name = %s",
                        (normalize_interest(name),))


def add_banned(schema: str, name: str) -> str | None:
    """Interdit une passion : la retire du catalogue ET de tous les
    profils existants, puis refuse les futures utilisations."""
    n = normalize_interest(name)
    if not n or len(n) > 60:
        return None
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO banned_interests (name) VALUES (%s) "
                "ON CONFLICT DO NOTHING", (n,))
            cur.execute("DELETE FROM session_interests WHERE name = %s", (n,))
            cur.execute("DELETE FROM user_interests WHERE interest = %s", (n,))
    return n


def remove_banned(schema: str, name: str) -> None:
    with sess_conn(schema) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM banned_interests WHERE name = %s",
                        (normalize_interest(name),))
