"""Isolated-execution dispatcher process boundary."""

import signal
import time
from types import FrameType

_stopping = False


def _request_stop(_signal: int, _frame: FrameType | None) -> None:
    global _stopping
    _stopping = True


def main() -> None:
    """Wait safely until Phase 3 execution handlers are registered."""

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    while not _stopping:
        time.sleep(1)


if __name__ == "__main__":
    main()
