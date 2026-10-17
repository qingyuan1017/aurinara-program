"""Structured CloudWatch embedded metric formatting."""

import json
import logging

from app.common.logging import JsonFormatter


def test_embedded_metric_is_the_top_level_log_event() -> None:
    payload = {
        "_aws": {"Timestamp": 1, "CloudWatchMetrics": []},
        "Environment": "test",
        "ExpiredLeases": 1,
    }
    record = logging.makeLogRecord(
        {"name": "aurinara.metrics", "msg": "operational metric", "embedded_metric": payload}
    )

    rendered = json.loads(JsonFormatter().format(record))

    assert rendered == payload
