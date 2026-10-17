"""Long-poll the platform projection queue and apply idempotent events."""

import signal
from types import FrameType

from app.common.logging import configure_logging
from app.config import get_settings
from app.database import create_database_engine, create_session_factory
from app.platform.projections import consume_once

_stopping = False


def _request_stop(_signal: int, _frame: FrameType | None) -> None:
    global _stopping
    _stopping = True


def main() -> None:
    """Consume messages until ECS requests a graceful shutdown."""

    settings = get_settings()
    configure_logging(settings.app_log_level)
    factory = create_session_factory(create_database_engine(settings))
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    while not _stopping:
        consume_once(settings, factory)


if __name__ == "__main__":
    main()
