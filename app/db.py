from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

from app.models import AutoReply, BotSettings, Broadcast, MessageMap, User
from app.utils import now_ts

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    language_code TEXT,
    is_banned INTEGER NOT NULL DEFAULT 0,
    is_blocked INTEGER NOT NULL DEFAULT 0,
    captcha_passed INTEGER NOT NULL DEFAULT 0,
    started INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    muted_until INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    forum_topic_id INTEGER,
    ui_lang TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_topic
    ON users(forum_topic_id) WHERE forum_topic_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS message_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    user_chat_id INTEGER NOT NULL,
    user_message_id INTEGER NOT NULL,
    admin_chat_id INTEGER NOT NULL,
    admin_message_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_map_admin
    ON message_map(admin_chat_id, admin_message_id);
CREATE INDEX IF NOT EXISTS idx_map_user
    ON message_map(user_chat_id, user_message_id);

CREATE TABLE IF NOT EXISTS auto_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    match_type TEXT NOT NULL DEFAULT 'contains',
    reply_text TEXT NOT NULL,
    is_enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS filter_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS link_allowlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS broadcasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    media_file_id TEXT,
    media_type TEXT,
    from_chat_id INTEGER,
    from_message_id INTEGER,
    interval_seconds INTEGER,
    last_sent_at INTEGER,
    next_send_at INTEGER,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rate_events (
    user_id INTEGER NOT NULL,
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_user_ts ON rate_events(user_id, ts);

CREATE TABLE IF NOT EXISTS captcha_challenges (
    user_id INTEGER PRIMARY KEY,
    answer TEXT NOT NULL,
    tries INTEGER NOT NULL DEFAULT 0,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stats (
    day TEXT NOT NULL,
    key TEXT NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, key)
);
"""


def _b(value: Any) -> bool:
    return bool(value)


def _user_from_row(row: aiosqlite.Row) -> User:
    return User(
        user_id=row["user_id"],
        username=row["username"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        language_code=row["language_code"],
        is_banned=_b(row["is_banned"]),
        is_blocked=_b(row["is_blocked"]),
        captcha_passed=_b(row["captcha_passed"]),
        started=_b(row["started"]),
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        message_count=row["message_count"],
        muted_until=row["muted_until"] or 0,
        notes=row["notes"],
        forum_topic_id=row["forum_topic_id"] if "forum_topic_id" in row.keys() else None,
        ui_lang=row["ui_lang"] if "ui_lang" in row.keys() else None,
    )


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        await self._migrate()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _migrate(self) -> None:
        rows = await self.fetchall("PRAGMA table_info(users)")
        names = {str(r[1]) for r in rows}
        if "forum_topic_id" not in names:
            await self.execute("ALTER TABLE users ADD COLUMN forum_topic_id INTEGER")
        if "ui_lang" not in names:
            await self.execute("ALTER TABLE users ADD COLUMN ui_lang TEXT")
        await self.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_topic
            ON users(forum_topic_id) WHERE forum_topic_id IS NOT NULL
            """
        )

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("database is not initialized")
        return self._conn

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Cursor:
        async with self._lock:
            cur = await self.conn.execute(sql, tuple(params))
            await self.conn.commit()
            return cur

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row | None:
        async with self._lock:
            cur = await self.conn.execute(sql, tuple(params))
            return await cur.fetchone()

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        async with self._lock:
            cur = await self.conn.execute(sql, tuple(params))
            return list(await cur.fetchall())

    # --- users ---

    async def upsert_user(
        self,
        user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        language_code: str | None,
    ) -> User:
        ts = now_ts()
        await self.execute(
            """
            INSERT INTO users (
                user_id, username, first_name, last_name, language_code,
                created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                language_code=excluded.language_code,
                last_seen_at=excluded.last_seen_at,
                is_blocked=0
            """,
            (user_id, username, first_name, last_name, language_code, ts, ts),
        )
        user = await self.get_user(user_id)
        assert user is not None
        return user

    async def get_user(self, user_id: int) -> User | None:
        row = await self.fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))
        return _user_from_row(row) if row else None

    async def find_user(self, query: str) -> User | None:
        query = query.strip().lstrip("@")
        if query.isdigit() or (query.startswith("-") and query[1:].isdigit()):
            return await self.get_user(int(query))
        row = await self.fetchone(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (query,),
        )
        return _user_from_row(row) if row else None

    async def set_flags(self, user_id: int, **flags: Any) -> None:
        if not flags:
            return
        allowed = {
            "is_banned",
            "is_blocked",
            "captcha_passed",
            "started",
            "muted_until",
            "notes",
            "forum_topic_id",
            "ui_lang",
        }
        parts = []
        values: list[Any] = []
        for key, value in flags.items():
            if key not in allowed:
                raise ValueError(f"unknown user flag: {key}")
            parts.append(f"{key}=?")
            if isinstance(value, bool):
                values.append(int(value))
            else:
                values.append(value)
        values.append(user_id)
        await self.execute(f"UPDATE users SET {', '.join(parts)} WHERE user_id=?", values)

    async def get_user_by_topic(self, topic_id: int) -> User | None:
        row = await self.fetchone(
            "SELECT * FROM users WHERE forum_topic_id=?",
            (topic_id,),
        )
        return _user_from_row(row) if row else None

    async def bump_message_count(self, user_id: int) -> None:
        await self.execute(
            "UPDATE users SET message_count = message_count + 1, last_seen_at=? WHERE user_id=?",
            (now_ts(), user_id),
        )

    async def list_users(
        self,
        offset: int = 0,
        limit: int = 8,
        *,
        banned_only: bool = False,
        search: str | None = None,
    ) -> list[User]:
        where = ["1=1"]
        params: list[Any] = []
        if banned_only:
            where.append("is_banned=1")
        if search:
            token = f"%{search.lstrip('@')}%"
            where.append(
                "(CAST(user_id AS TEXT) LIKE ? OR IFNULL(username,'') LIKE ? OR IFNULL(first_name,'') LIKE ?)"
            )
            params.extend([token, token, token])
        params.extend([limit, offset])
        rows = await self.fetchall(
            f"""
            SELECT * FROM users
            WHERE {' AND '.join(where)}
            ORDER BY last_seen_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        )
        return [_user_from_row(r) for r in rows]

    async def count_users(
        self,
        *,
        banned_only: bool = False,
        search: str | None = None,
        active_only: bool = False,
    ) -> int:
        where = ["1=1"]
        params: list[Any] = []
        if banned_only:
            where.append("is_banned=1")
        if active_only:
            where.append("started=1 AND is_banned=0 AND is_blocked=0")
        if search:
            token = f"%{search.lstrip('@')}%"
            where.append(
                "(CAST(user_id AS TEXT) LIKE ? OR IFNULL(username,'') LIKE ? OR IFNULL(first_name,'') LIKE ?)"
            )
            params.extend([token, token, token])
        row = await self.fetchone(
            f"SELECT COUNT(*) AS n FROM users WHERE {' AND '.join(where)}",
            params,
        )
        return int(row["n"]) if row else 0

    async def broadcast_targets(self) -> list[int]:
        rows = await self.fetchall(
            """
            SELECT user_id FROM users
            WHERE started=1 AND is_banned=0 AND is_blocked=0
            """
        )
        return [int(r["user_id"]) for r in rows]

    # --- settings ---

    async def get_setting(self, key: str) -> str | None:
        row = await self.fetchone("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self.execute(
            """
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )

    async def load_bot_settings(self) -> BotSettings:
        raw = await self.get_setting("bot")
        if not raw:
            settings = BotSettings()
            await self.save_bot_settings(settings)
            return settings
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return BotSettings()
        if not isinstance(data, dict):
            return BotSettings()
        return BotSettings.from_dict(data)

    async def save_bot_settings(self, settings: BotSettings) -> None:
        await self.set_setting("bot", json.dumps(settings.to_dict(), ensure_ascii=False))

    async def extra_admin_ids(self) -> list[int]:
        raw = await self.get_setting("extra_admin_ids")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [int(x) for x in data]

    async def set_extra_admin_ids(self, ids: list[int]) -> None:
        await self.set_setting("extra_admin_ids", json.dumps(ids))

    # --- message map ---

    async def add_map(
        self,
        *,
        user_id: int,
        user_chat_id: int,
        user_message_id: int,
        admin_chat_id: int,
        admin_message_id: int,
        direction: str,
    ) -> None:
        await self.execute(
            """
            INSERT INTO message_map (
                user_id, user_chat_id, user_message_id,
                admin_chat_id, admin_message_id, direction, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                user_chat_id,
                user_message_id,
                admin_chat_id,
                admin_message_id,
                direction,
                now_ts(),
            ),
        )

    async def map_by_admin(self, admin_chat_id: int, admin_message_id: int) -> MessageMap | None:
        row = await self.fetchone(
            """
            SELECT * FROM message_map
            WHERE admin_chat_id=? AND admin_message_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (admin_chat_id, admin_message_id),
        )
        return self._map_from_row(row) if row else None

    async def maps_for_user_message(self, user_chat_id: int, user_message_id: int) -> list[MessageMap]:
        rows = await self.fetchall(
            """
            SELECT * FROM message_map
            WHERE user_chat_id=? AND user_message_id=? AND direction='in'
            """,
            (user_chat_id, user_message_id),
        )
        return [self._map_from_row(r) for r in rows]

    @staticmethod
    def _map_from_row(row: aiosqlite.Row) -> MessageMap:
        return MessageMap(
            id=row["id"],
            user_id=row["user_id"],
            user_chat_id=row["user_chat_id"],
            user_message_id=row["user_message_id"],
            admin_chat_id=row["admin_chat_id"],
            admin_message_id=row["admin_message_id"],
            direction=row["direction"],
            created_at=row["created_at"],
        )

    # --- auto replies ---

    async def add_auto_reply(self, keyword: str, match_type: str, reply_text: str) -> int:
        cur = await self.execute(
            """
            INSERT INTO auto_replies(keyword, match_type, reply_text, is_enabled)
            VALUES (?, ?, ?, 1)
            """,
            (keyword, match_type, reply_text),
        )
        return int(cur.lastrowid)

    async def list_auto_replies(self) -> list[AutoReply]:
        rows = await self.fetchall("SELECT * FROM auto_replies ORDER BY id")
        return [
            AutoReply(
                id=r["id"],
                keyword=r["keyword"],
                match_type=r["match_type"],
                reply_text=r["reply_text"],
                is_enabled=_b(r["is_enabled"]),
            )
            for r in rows
        ]

    async def delete_auto_reply(self, item_id: int) -> None:
        await self.execute("DELETE FROM auto_replies WHERE id=?", (item_id,))

    async def toggle_auto_reply(self, item_id: int) -> None:
        await self.execute(
            "UPDATE auto_replies SET is_enabled = CASE is_enabled WHEN 1 THEN 0 ELSE 1 END WHERE id=?",
            (item_id,),
        )

    # --- filter keywords / allowlist ---

    async def add_filter_keyword(self, keyword: str) -> bool:
        try:
            await self.execute(
                "INSERT INTO filter_keywords(keyword) VALUES (?)",
                (keyword,),
            )
            return True
        except aiosqlite.IntegrityError:
            return False

    async def list_filter_keywords(self) -> list[tuple[int, str]]:
        rows = await self.fetchall("SELECT id, keyword FROM filter_keywords ORDER BY id")
        return [(int(r["id"]), str(r["keyword"])) for r in rows]

    async def delete_filter_keyword(self, item_id: int) -> None:
        await self.execute("DELETE FROM filter_keywords WHERE id=?", (item_id,))

    async def add_allow_domain(self, domain: str) -> bool:
        try:
            await self.execute(
                "INSERT INTO link_allowlist(domain) VALUES (?)",
                (domain,),
            )
            return True
        except aiosqlite.IntegrityError:
            return False

    async def list_allow_domains(self) -> list[tuple[int, str]]:
        rows = await self.fetchall("SELECT id, domain FROM link_allowlist ORDER BY id")
        return [(int(r["id"]), str(r["domain"])) for r in rows]

    async def delete_allow_domain(self, item_id: int) -> None:
        await self.execute("DELETE FROM link_allowlist WHERE id=?", (item_id,))

    # --- broadcasts ---

    async def add_broadcast(
        self,
        *,
        text: str | None,
        media_file_id: str | None,
        media_type: str | None,
        from_chat_id: int | None,
        from_message_id: int | None,
        interval_seconds: int | None,
        next_send_at: int | None,
        created_by: int | None,
        is_enabled: bool = True,
    ) -> int:
        cur = await self.execute(
            """
            INSERT INTO broadcasts (
                text, media_file_id, media_type, from_chat_id, from_message_id,
                interval_seconds, last_sent_at, next_send_at, is_enabled,
                created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                text,
                media_file_id,
                media_type,
                from_chat_id,
                from_message_id,
                interval_seconds,
                next_send_at,
                int(is_enabled),
                created_by,
                now_ts(),
            ),
        )
        return int(cur.lastrowid)

    async def get_broadcast(self, item_id: int) -> Broadcast | None:
        row = await self.fetchone("SELECT * FROM broadcasts WHERE id=?", (item_id,))
        return self._broadcast_from_row(row) if row else None

    async def list_broadcasts(self) -> list[Broadcast]:
        rows = await self.fetchall("SELECT * FROM broadcasts ORDER BY id DESC")
        return [self._broadcast_from_row(r) for r in rows]

    async def list_enabled_repeating_broadcasts(self) -> list[Broadcast]:
        rows = await self.fetchall(
            """
            SELECT * FROM broadcasts
            WHERE is_enabled=1 AND interval_seconds IS NOT NULL AND interval_seconds > 0
            """
        )
        return [self._broadcast_from_row(r) for r in rows]

    async def mark_broadcast_sent(self, item_id: int, next_send_at: int | None) -> None:
        ts = now_ts()
        await self.execute(
            "UPDATE broadcasts SET last_sent_at=?, next_send_at=? WHERE id=?",
            (ts, next_send_at, item_id),
        )

    async def set_broadcast_enabled(self, item_id: int, enabled: bool) -> None:
        await self.execute(
            "UPDATE broadcasts SET is_enabled=? WHERE id=?",
            (int(enabled), item_id),
        )

    async def delete_broadcast(self, item_id: int) -> None:
        await self.execute("DELETE FROM broadcasts WHERE id=?", (item_id,))

    @staticmethod
    def _broadcast_from_row(row: aiosqlite.Row) -> Broadcast:
        return Broadcast(
            id=row["id"],
            text=row["text"],
            media_file_id=row["media_file_id"],
            media_type=row["media_type"],
            from_chat_id=row["from_chat_id"],
            from_message_id=row["from_message_id"],
            interval_seconds=row["interval_seconds"],
            last_sent_at=row["last_sent_at"],
            next_send_at=row["next_send_at"],
            is_enabled=_b(row["is_enabled"]),
            created_by=row["created_by"],
            created_at=row["created_at"],
        )

    # --- captcha ---

    async def set_captcha(self, user_id: int, answer: str, expires_at: int) -> None:
        await self.execute(
            """
            INSERT INTO captcha_challenges(user_id, answer, tries, expires_at)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                answer=excluded.answer, tries=0, expires_at=excluded.expires_at
            """,
            (user_id, answer, expires_at),
        )

    async def get_captcha(self, user_id: int) -> tuple[str, int, int] | None:
        row = await self.fetchone(
            "SELECT answer, tries, expires_at FROM captcha_challenges WHERE user_id=?",
            (user_id,),
        )
        if not row:
            return None
        return str(row["answer"]), int(row["tries"]), int(row["expires_at"])

    async def bump_captcha_tries(self, user_id: int) -> int:
        await self.execute(
            "UPDATE captcha_challenges SET tries = tries + 1 WHERE user_id=?",
            (user_id,),
        )
        row = await self.fetchone(
            "SELECT tries FROM captcha_challenges WHERE user_id=?",
            (user_id,),
        )
        return int(row["tries"]) if row else 0

    async def delete_captcha(self, user_id: int) -> None:
        await self.execute("DELETE FROM captcha_challenges WHERE user_id=?", (user_id,))

    # --- rate limit ---

    async def add_rate_event(self, user_id: int, ts: int) -> None:
        await self.execute("INSERT INTO rate_events(user_id, ts) VALUES (?, ?)", (user_id, ts))

    async def count_rate_events(self, user_id: int, since: int) -> int:
        row = await self.fetchone(
            "SELECT COUNT(*) AS n FROM rate_events WHERE user_id=? AND ts>=?",
            (user_id, since),
        )
        return int(row["n"]) if row else 0

    async def prune_rate_events(self, before: int) -> None:
        await self.execute("DELETE FROM rate_events WHERE ts < ?", (before,))

    # --- stats ---

    async def incr_stat(self, key: str, amount: int = 1, day: str | None = None) -> None:
        from app.utils import today_key

        day = day or today_key()
        await self.execute(
            """
            INSERT INTO stats(day, key, value) VALUES (?, ?, ?)
            ON CONFLICT(day, key) DO UPDATE SET value = value + excluded.value
            """,
            (day, key, amount),
        )

    async def get_stats(self, day: str | None = None) -> dict[str, int]:
        from app.utils import today_key

        day = day or today_key()
        rows = await self.fetchall("SELECT key, value FROM stats WHERE day=?", (day,))
        return {str(r["key"]): int(r["value"]) for r in rows}
