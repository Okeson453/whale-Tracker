"""Async database engine and session management."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_db_url
from app.state.models import Base

_engine = None
_async_session_maker = None


def _get_engine():
    global _engine
    if _engine is None:
        # statement_cache_size=0 disables prepared statement caching,
        # required when Postgres is behind PgBouncer in transaction/statement pooling mode
        _engine = create_async_engine(
            get_db_url(),
            echo=False,
            future=True,
            connect_args={"statement_cache_size": 0},
        )
    return _engine


def get_session_maker():
    global _async_session_maker
    if _async_session_maker is None:
        _async_session_maker = async_sessionmaker(
            _get_engine(), expire_on_commit=False
        )
    return _async_session_maker


async def init_db() -> None:
    """Create tables if they do not exist."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db_session():
    """FastAPI dependency yielding an async DB session."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
