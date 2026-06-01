from app.utils.config import Settings


class BaseService:
    """Base service dependency for future domain services."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
