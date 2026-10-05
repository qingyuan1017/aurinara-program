"""Outbound integration dispatcher process boundary."""

import signal
import time
from types import FrameType

from app.composition import build_module_registry
from app.config import get_settings
from app.database import create_database_engine, create_session_factory
from app.integration.delivery import DeliveryService

_stopping = False


def _request_stop(_signal: int, _frame: FrameType | None) -> None:
    global _stopping
    _stopping = True


def main() -> None:
    """Schedule and deliver committed public events with bounded retries."""

    settings = get_settings()
    factory = create_session_factory(create_database_engine(settings))
    service = DeliveryService(build_module_registry())
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    while not _stopping:
        with factory.begin() as session:
            scheduled = service.schedule(session)
        with factory.begin() as session:
            delivered = service.deliver_one(session, settings)
        if not scheduled and not delivered:
            time.sleep(1)


if __name__ == "__main__":
    main()
