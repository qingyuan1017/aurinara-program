"""Consume canonical platform events from the configured SQS queue."""

import argparse

from app.config import get_settings
from app.database import create_database_engine, create_session_factory
from app.platform.projections import consume_once


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="Continue long-polling for events")
    args = parser.parse_args()

    settings = get_settings()
    factory = create_session_factory(create_database_engine(settings))
    while True:
        consumed = consume_once(settings, factory)
        if not args.watch:
            print(f"consumed={consumed}")
            return


if __name__ == "__main__":
    main()
