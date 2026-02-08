from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """Minimal JSON logs for production-ish observability (no external deps)."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Common structured fields. These come from logger calls via `extra={...}`.
        for key in (
            "event",
            "request_id",
            "run_id",
            "agent",
            "latency_ms",
            "status_code",
            "method",
            "path",
            "risk_tier",
            "escalation_required",
            "reasoning_backend",
        ):
            if hasattr(record, key):
                value = getattr(record, key)
                if value is not None:
                    payload[key] = value

        if record.exc_info:
            exc_type = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
            payload["exc_type"] = exc_type
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(*, level: str = "INFO", json_logs: bool = False) -> None:
    """Configure root logging for CLI/server entry points."""

    level_value = getattr(logging, level.strip().upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level_value)

    # Avoid duplicated handlers when reconfiguring in the same process (tests, notebooks).
    root.handlers[:] = []

    handler = logging.StreamHandler()
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)

