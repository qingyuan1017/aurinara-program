"""Bounded local webhook receiver used only by development and integration tests."""

from threading import Lock

from fastapi import FastAPI, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(title="Aurinara Integration Test Receiver", docs_url=None, redoc_url=None)
_lock = Lock()
_events: dict[str, dict[str, object]] = {}
_failure_statuses: list[int] = []
_max_body_bytes = 65_536


class FailureSequence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statuses: list[int] = Field(max_length=20)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/events")
async def receive_event(
    request: Request,
    response: Response,
    event_id: str = Header(alias="X-Aurinara-Event-ID"),
) -> dict[str, object]:
    body = await request.body()
    if len(body) > _max_body_bytes:
        response.status_code = 413
        return {"accepted": False}
    with _lock:
        _events.setdefault(
            event_id,
            {
                "event_id": event_id,
                "body": body.decode("utf-8", errors="replace"),
                "headers": {
                    name.lower(): value
                    for name, value in request.headers.items()
                    if name.lower().startswith("x-aurinara-")
                },
                "deliveries": 0,
            },
        )
        prior_deliveries = _events[event_id]["deliveries"]
        _events[event_id]["deliveries"] = (
            prior_deliveries + 1 if isinstance(prior_deliveries, int) else 1
        )
        response.status_code = _failure_statuses.pop(0) if _failure_statuses else 202
    return {"accepted": response.status_code < 300, "event_id": event_id}


@app.get("/events")
def list_events() -> dict[str, list[dict[str, object]]]:
    with _lock:
        return {"items": list(_events.values())}


@app.put("/failure-sequence")
def set_failure_sequence(command: FailureSequence) -> dict[str, list[int]]:
    if any(status < 400 or status > 599 for status in command.statuses):
        return {"statuses": []}
    with _lock:
        _failure_statuses[:] = command.statuses
    return {"statuses": command.statuses}


@app.delete("/events", status_code=204)
def reset_events() -> None:
    with _lock:
        _events.clear()
        _failure_statuses.clear()
