from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_config

_engine = None
_async_session = None


def _get_engine():
    global _engine
    if _engine is None:
        config = get_config()
        _engine = create_async_engine(config.database_url, echo=config.debug)
    return _engine


def _get_session_factory():
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(
            _get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _async_session


async def init_db():
    """Create all tables on startup."""
    from src.storage.models import Base

    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    session_factory = _get_session_factory()
    async with session_factory() as session:
        yield session


def reset_engine():
    """Reset the engine (useful for testing with different configs)."""
    global _engine, _async_session
    _engine = None
    _async_session = None
