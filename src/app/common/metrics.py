"""CloudWatch embedded metrics without a network call in application code."""

import logging
import time

logger = logging.getLogger("aurinara.metrics")


def emit_metric(
    name: str,
    value: float,
    *,
    environment: str,
    unit: str = "Count",
    dimensions: dict[str, str] | None = None,
) -> None:
    """Write one structured EMF event for the ECS log driver to publish."""

    dimension_values = {"Environment": environment, **(dimensions or {})}
    payload: dict[str, object] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "Aurinara",
                    "Dimensions": [list(dimension_values)],
                    "Metrics": [{"Name": name, "Unit": unit}],
                }
            ],
        },
        **dimension_values,
        name: value,
    }
    logger.info("operational metric", extra={"embedded_metric": payload})
