from collections.abc import AsyncIterator


async def get_database_session() -> AsyncIterator[None]:
    """Placeholder dependency for future database sessions."""
    yield None
