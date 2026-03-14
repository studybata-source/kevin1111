from __future__ import annotations

from pathlib import Path

from sqlalchemy import (
    BIGINT,
    BOOLEAN,
    INTEGER,
    TEXT,
    Column,
    MetaData,
    Table,
    and_,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.sql import Select


metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("user_id", BIGINT, primary_key=True),
    Column("username", TEXT),
    Column("full_name", TEXT, nullable=False),
    Column("language_code", TEXT),
    Column("created_at", TEXT, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", TEXT, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

user_settings = Table(
    "user_settings",
    metadata,
    Column("user_id", BIGINT, primary_key=True),
    Column("quality_preset", TEXT, nullable=False, server_default=text("'best'")),
    Column("audio_format", TEXT, nullable=False, server_default=text("'mp3'")),
    Column("updated_at", TEXT, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

chats = Table(
    "chats",
    metadata,
    Column("chat_id", BIGINT, primary_key=True),
    Column("chat_type", TEXT, nullable=False),
    Column("title", TEXT),
    Column("username", TEXT),
    Column("is_active", BOOLEAN, nullable=False, server_default=text("1")),
    Column("created_at", TEXT, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", TEXT, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

search_history = Table(
    "search_history",
    metadata,
    Column("id", INTEGER, primary_key=True, autoincrement=True),
    Column("user_id", BIGINT, nullable=False),
    Column("query", TEXT, nullable=False),
    Column("result_count", INTEGER, nullable=False, server_default=text("0")),
    Column("created_at", TEXT, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

download_history = Table(
    "download_history",
    metadata,
    Column("id", INTEGER, primary_key=True, autoincrement=True),
    Column("user_id", BIGINT),
    Column("chat_id", BIGINT, nullable=False),
    Column("query", TEXT, nullable=False),
    Column("source_key", TEXT, nullable=False),
    Column("title", TEXT, nullable=False),
    Column("performer", TEXT),
    Column("status", TEXT, nullable=False),
    Column("created_at", TEXT, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

app_meta = Table(
    "app_meta",
    metadata,
    Column("key", TEXT, primary_key=True),
    Column("value", TEXT, nullable=False),
    Column("updated_at", TEXT, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

audio_cache = Table(
    "audio_cache",
    metadata,
    Column("source_key", TEXT, primary_key=True),
    Column("telegram_file_id", TEXT, nullable=False),
    Column("title", TEXT, nullable=False),
    Column("performer", TEXT),
    Column("duration_seconds", INTEGER),
    Column("file_size_bytes", BIGINT),
    Column("created_at", TEXT, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", TEXT, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

query_source_cache = Table(
    "query_source_cache",
    metadata,
    Column("query_key", TEXT, primary_key=True),
    Column("source_key", TEXT, nullable=False),
    Column("updated_at", TEXT, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

search_sessions = Table(
    "search_sessions",
    metadata,
    Column("token", TEXT, primary_key=True),
    Column("kind", TEXT, nullable=False),
    Column("payload_json", TEXT, nullable=False),
    Column("expires_at", BIGINT, nullable=False),
    Column("updated_at", TEXT, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)


class Database:
    def __init__(
        self,
        dsn_or_path: str | Path,
        *,
        default_quality_preset: str = "best",
        default_audio_format: str = "mp3",
        pool_size: int = 20,
        max_overflow: int = 40,
        pool_timeout_sec: float = 30.0,
    ) -> None:
        self._database_url = self._build_database_url(dsn_or_path)
        self._is_postgres = self._database_url.startswith("postgresql+asyncpg://")
        self._engine: AsyncEngine | None = None
        self._default_quality_preset = default_quality_preset
        self._default_audio_format = default_audio_format
        self._pool_size = max(1, pool_size)
        self._max_overflow = max(0, max_overflow)
        self._pool_timeout_sec = max(1.0, pool_timeout_sec)

    async def connect(self) -> None:
        engine_kwargs: dict[str, object] = {
            "future": True,
            "pool_pre_ping": True,
        }
        if self._is_postgres:
            engine_kwargs.update(
                pool_size=self._pool_size,
                max_overflow=self._max_overflow,
                pool_timeout=self._pool_timeout_sec,
            )
        self._engine = create_async_engine(self._database_url, **engine_kwargs)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    async def initialize(self) -> None:
        async with self._begin() as conn:
            await conn.run_sync(metadata.create_all)
            await self._run_migrations(conn)
            await self._ensure_indexes(conn)

    async def upsert_user(
        self,
        user_id: int,
        username: str | None,
        full_name: str,
        language_code: str | None,
    ) -> None:
        async with self._begin() as conn:
            await conn.execute(
                self._upsert_statement(
                    users,
                    {
                        "user_id": user_id,
                        "username": username,
                        "full_name": full_name,
                        "language_code": language_code,
                    },
                    index_elements=[users.c.user_id],
                    set_={
                        "username": username,
                        "full_name": full_name,
                        "language_code": language_code,
                        "updated_at": text("CURRENT_TIMESTAMP"),
                    },
                )
            )
            await conn.execute(
                self._upsert_statement(
                    user_settings,
                    {
                        "user_id": user_id,
                        "quality_preset": self._default_quality_preset,
                        "audio_format": self._default_audio_format,
                    },
                    index_elements=[user_settings.c.user_id],
                    do_nothing=True,
                )
            )

    async def get_quality_preset(self, user_id: int) -> str:
        row = await self._fetch_one(
            select(user_settings.c.quality_preset).where(user_settings.c.user_id == user_id)
        )
        if not row:
            return self._default_quality_preset
        return str(row["quality_preset"])

    async def set_quality_preset(self, user_id: int, preset: str) -> None:
        async with self._begin() as conn:
            await conn.execute(
                self._upsert_statement(
                    user_settings,
                    {
                        "user_id": user_id,
                        "quality_preset": preset,
                        "audio_format": self._default_audio_format,
                    },
                    index_elements=[user_settings.c.user_id],
                    set_={
                        "quality_preset": preset,
                        "updated_at": text("CURRENT_TIMESTAMP"),
                    },
                )
            )

    async def get_audio_format(self, user_id: int) -> str:
        row = await self._fetch_one(
            select(user_settings.c.audio_format).where(user_settings.c.user_id == user_id)
        )
        if not row:
            return self._default_audio_format
        return str(row["audio_format"])

    async def set_audio_format(self, user_id: int, audio_format: str) -> None:
        async with self._begin() as conn:
            await conn.execute(
                self._upsert_statement(
                    user_settings,
                    {
                        "user_id": user_id,
                        "quality_preset": self._default_quality_preset,
                        "audio_format": audio_format,
                    },
                    index_elements=[user_settings.c.user_id],
                    set_={
                        "audio_format": audio_format,
                        "updated_at": text("CURRENT_TIMESTAMP"),
                    },
                )
            )

    async def get_user_delivery_settings(self, user_id: int) -> dict[str, str]:
        row = await self._fetch_one(
            select(user_settings.c.quality_preset, user_settings.c.audio_format).where(user_settings.c.user_id == user_id)
        )
        if not row:
            return {
                "quality_preset": self._default_quality_preset,
                "audio_format": self._default_audio_format,
            }
        return {
            "quality_preset": str(row["quality_preset"]),
            "audio_format": str(row["audio_format"]),
        }

    async def upsert_chat(
        self,
        chat_id: int,
        chat_type: str,
        title: str | None,
        username: str | None,
        is_active: bool = True,
    ) -> None:
        async with self._begin() as conn:
            await conn.execute(
                self._upsert_statement(
                    chats,
                    {
                        "chat_id": chat_id,
                        "chat_type": chat_type,
                        "title": title,
                        "username": username,
                        "is_active": bool(is_active),
                    },
                    index_elements=[chats.c.chat_id],
                    set_={
                        "chat_type": chat_type,
                        "title": title,
                        "username": username,
                        "is_active": bool(is_active),
                        "updated_at": text("CURRENT_TIMESTAMP"),
                    },
                )
            )

    async def set_chat_active(self, chat_id: int, is_active: bool) -> None:
        async with self._begin() as conn:
            await conn.execute(
                chats.update()
                .where(chats.c.chat_id == chat_id)
                .values(is_active=bool(is_active), updated_at=text("CURRENT_TIMESTAMP"))
            )

    async def log_search(self, user_id: int, query: str, result_count: int) -> None:
        async with self._begin() as conn:
            await conn.execute(
                search_history.insert().values(
                    user_id=user_id,
                    query=query,
                    result_count=result_count,
                )
            )

    async def log_download(
        self,
        chat_id: int,
        query: str,
        source_key: str,
        title: str,
        performer: str | None,
        status: str,
        user_id: int | None = None,
    ) -> None:
        async with self._begin() as conn:
            await conn.execute(
                download_history.insert().values(
                    user_id=user_id,
                    chat_id=chat_id,
                    query=query,
                    source_key=source_key,
                    title=title,
                    performer=performer,
                    status=status,
                )
            )

    async def get_recent_searches(self, user_id: int, limit: int = 8) -> list[dict[str, str | int]]:
        rows = await self._fetch_all(
            select(
                search_history.c.query,
                search_history.c.result_count,
                search_history.c.created_at,
            )
            .where(search_history.c.user_id == user_id)
            .order_by(search_history.c.id.desc())
            .limit(limit)
        )
        return [
            {
                "query": row["query"],
                "result_count": row["result_count"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def get_owner_user_id(self) -> int | None:
        row = await self._fetch_one(select(app_meta.c.value).where(app_meta.c.key == "owner_user_id"))
        if not row:
            return None
        return int(row["value"])

    async def set_owner_user_id(self, user_id: int) -> None:
        async with self._begin() as conn:
            await conn.execute(
                self._upsert_statement(
                    app_meta,
                    {"key": "owner_user_id", "value": str(user_id)},
                    index_elements=[app_meta.c.key],
                    set_={"value": str(user_id), "updated_at": text("CURRENT_TIMESTAMP")},
                )
            )

    async def get_broadcast_targets(self, groups_only: bool = False) -> list[dict[str, str | int]]:
        statement = select(
            chats.c.chat_id,
            chats.c.chat_type,
            chats.c.title,
            chats.c.username,
        ).where(chats.c.is_active.is_(True))
        if groups_only:
            statement = statement.where(chats.c.chat_type.in_(("group", "supergroup")))
        statement = statement.order_by(chats.c.updated_at.desc())
        rows = await self._fetch_all(statement)
        return [
            {
                "chat_id": row["chat_id"],
                "chat_type": row["chat_type"],
                "title": row["title"],
                "username": row["username"],
            }
            for row in rows
        ]

    async def get_stats(self) -> dict[str, int]:
        users_count = await self._fetch_scalar(select(func.count()).select_from(users))
        active_chats = await self._fetch_scalar(
            select(func.count()).select_from(chats).where(chats.c.is_active.is_(True))
        )
        groups_count = await self._fetch_scalar(
            select(func.count()).select_from(chats).where(
                and_(chats.c.is_active.is_(True), chats.c.chat_type.in_(("group", "supergroup")))
            )
        )
        searches_count = await self._fetch_scalar(select(func.count()).select_from(search_history))
        downloads_count = await self._fetch_scalar(select(func.count()).select_from(download_history))
        return {
            "users": int(users_count or 0),
            "active_chats": int(active_chats or 0),
            "groups": int(groups_count or 0),
            "searches": int(searches_count or 0),
            "downloads": int(downloads_count or 0),
        }

    async def get_cached_audio(self, source_key: str) -> dict[str, str | int] | None:
        row = await self._fetch_one(
            select(
                audio_cache.c.telegram_file_id,
                audio_cache.c.title,
                audio_cache.c.performer,
                audio_cache.c.duration_seconds,
                audio_cache.c.file_size_bytes,
            ).where(audio_cache.c.source_key == source_key)
        )
        if not row:
            return None
        return {
            "telegram_file_id": row["telegram_file_id"],
            "title": row["title"],
            "performer": row["performer"],
            "duration_seconds": row["duration_seconds"],
            "file_size_bytes": row["file_size_bytes"],
        }

    async def upsert_cached_audio(
        self,
        source_key: str,
        telegram_file_id: str,
        title: str,
        performer: str | None,
        duration_seconds: int | None,
        file_size_bytes: int | None = None,
    ) -> None:
        async with self._begin() as conn:
            await conn.execute(
                self._upsert_statement(
                    audio_cache,
                    {
                        "source_key": source_key,
                        "telegram_file_id": telegram_file_id,
                        "title": title,
                        "performer": performer,
                        "duration_seconds": duration_seconds,
                        "file_size_bytes": file_size_bytes,
                    },
                    index_elements=[audio_cache.c.source_key],
                    set_={
                        "telegram_file_id": telegram_file_id,
                        "title": title,
                        "performer": performer,
                        "duration_seconds": duration_seconds,
                        "file_size_bytes": file_size_bytes,
                        "updated_at": text("CURRENT_TIMESTAMP"),
                    },
                )
            )

    async def get_query_source_key(self, query_key: str) -> str | None:
        row = await self._fetch_one(
            select(query_source_cache.c.source_key).where(query_source_cache.c.query_key == query_key)
        )
        if not row:
            return None
        return str(row["source_key"])

    async def upsert_query_source(self, query_key: str, source_key: str) -> None:
        async with self._begin() as conn:
            await conn.execute(
                self._upsert_statement(
                    query_source_cache,
                    {"query_key": query_key, "source_key": source_key},
                    index_elements=[query_source_cache.c.query_key],
                    set_={"source_key": source_key, "updated_at": text("CURRENT_TIMESTAMP")},
                )
            )

    async def upsert_search_session(
        self,
        token: str,
        kind: str,
        payload_json: str,
        expires_at: int,
    ) -> None:
        async with self._begin() as conn:
            await conn.execute(
                self._upsert_statement(
                    search_sessions,
                    {
                        "token": token,
                        "kind": kind,
                        "payload_json": payload_json,
                        "expires_at": expires_at,
                    },
                    index_elements=[search_sessions.c.token],
                    set_={
                        "kind": kind,
                        "payload_json": payload_json,
                        "expires_at": expires_at,
                        "updated_at": text("CURRENT_TIMESTAMP"),
                    },
                )
            )

    async def get_search_session(self, token: str, kind: str, *, now_epoch: int) -> str | None:
        row = await self._fetch_one(
            select(search_sessions.c.payload_json)
            .where(search_sessions.c.token == token)
            .where(search_sessions.c.kind == kind)
            .where(search_sessions.c.expires_at > now_epoch)
        )
        if not row:
            return None
        return str(row["payload_json"])

    async def delete_expired_search_sessions(self, now_epoch: int) -> None:
        async with self._begin() as conn:
            await conn.execute(search_sessions.delete().where(search_sessions.c.expires_at <= now_epoch))

    def _build_database_url(self, dsn_or_path: str | Path) -> str:
        if isinstance(dsn_or_path, Path):
            return f"sqlite+aiosqlite:///{dsn_or_path.resolve().as_posix()}"
        text_value = str(dsn_or_path).strip()
        if text_value.startswith("postgresql://"):
            return text_value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if text_value.startswith("postgres://"):
            return text_value.replace("postgres://", "postgresql+asyncpg://", 1)
        if text_value.startswith("sqlite://"):
            return text_value.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return f"sqlite+aiosqlite:///{Path(text_value).resolve().as_posix()}"

    def _insert(self, table: Table):
        if self._is_postgres:
            return pg_insert(table)
        return sqlite_insert(table)

    def _upsert_statement(
        self,
        table: Table,
        values: dict[str, object],
        *,
        index_elements: list[Column[object]],
        set_: dict[str, object] | None = None,
        do_nothing: bool = False,
    ):
        statement = self._insert(table).values(**values)
        if do_nothing:
            return statement.on_conflict_do_nothing(index_elements=index_elements)
        if set_ is None:
            raise ValueError("set_ is required unless do_nothing is enabled.")
        return statement.on_conflict_do_update(index_elements=index_elements, set_=set_)

    async def _run_migrations(self, conn: AsyncConnection) -> None:
        existing_user_settings = await conn.run_sync(
            lambda sync_conn: {col["name"] for col in inspect(sync_conn).get_columns("user_settings")}
        )
        if "audio_format" not in existing_user_settings:
            await conn.execute(text("ALTER TABLE user_settings ADD COLUMN audio_format TEXT DEFAULT 'mp3' NOT NULL"))

        existing_audio_cache = await conn.run_sync(
            lambda sync_conn: {col["name"] for col in inspect(sync_conn).get_columns("audio_cache")}
        )
        if "file_size_bytes" not in existing_audio_cache:
            await conn.execute(text("ALTER TABLE audio_cache ADD COLUMN file_size_bytes BIGINT"))

    async def _ensure_indexes(self, conn: AsyncConnection) -> None:
        statements = (
            "CREATE INDEX IF NOT EXISTS idx_search_history_user_created ON search_history(user_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_download_history_chat_created ON download_history(chat_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_chats_type_active ON chats(chat_type, is_active)",
            "CREATE INDEX IF NOT EXISTS idx_search_sessions_expires ON search_sessions(expires_at)",
        )
        for statement in statements:
            await conn.execute(text(statement))

    def _require_engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Database connection has not been opened.")
        return self._engine

    def _begin(self):
        return self._require_engine().begin()

    async def _fetch_one(self, statement: Select):
        async with self._require_engine().connect() as conn:
            result = await conn.execute(statement)
            row = result.mappings().first()
            return dict(row) if row is not None else None

    async def _fetch_all(self, statement: Select) -> list[dict[str, object]]:
        async with self._require_engine().connect() as conn:
            result = await conn.execute(statement)
            return [dict(row) for row in result.mappings().all()]

    async def _fetch_scalar(self, statement: Select) -> object:
        async with self._require_engine().connect() as conn:
            result = await conn.execute(statement)
            return result.scalar()
