"""Outbound integration events (n8n), disabled by default.

``N8N_WEBHOOK_BASE_URL`` empty = the whole feature is a no-op: no event id is
built, no Celery task is queued. When it is set, ``N8N_WEBHOOK_SECRET`` is
required at startup (config/settings.py) and every event is signed.

The payload is deliberately minimal and privacy-safe: no full URL, no email,
no user name. Only the scan domain, verdicts, risk index, detection source,
the event time and a review link built from FRONTEND_URL.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid
from functools import partial
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from audit.models import AuditLog

from .events import (
    EVENT_PATHS,
    SCAN_CONFIRMED,
    SCAN_NEEDS_REVIEW,
    TEST_EVENT,
)
from .tasks import deliver_event

logger = logging.getLogger(__name__)

TEST_EVENT_PAYLOAD = {
    "message": "Harmless test event emitted by manage.py send_test_event",
    "origin": "management_command",
}

HEALTH_TIMEOUT_SECONDS = 2.0
RECENT_EVENTS_LIMIT = 20


def is_enabled() -> bool:
    """True only when a base URL is configured (empty = feature disabled)."""
    return bool((settings.N8N_WEBHOOK_BASE_URL or "").strip())


def emit_event(event_type: str, payload: dict[str, Any] | None = None) -> str | None:
    """Build one event and enqueue its delivery AFTER the current commit.

    Returns the event id, or None when the feature is disabled or the event
    type is unknown. Never takes a destination: the host is fixed by settings.
    """
    if not is_enabled():
        return None
    if event_type not in EVENT_PATHS:
        logger.warning("integration.unknown_event event_type=%s", event_type)
        return None

    event = {
        "id": str(uuid.uuid4()),
        "type": event_type,
        "occurred_at": timezone.now().isoformat(),
        "data": payload or {},
    }
    transaction.on_commit(partial(deliver_event.delay, event))
    return event["id"]


def _scan_payload(scan, *, review_reason: str | None = None) -> dict[str, Any]:
    """Minimal, privacy-safe scan payload (never the URL or a user identity)."""
    payload: dict[str, Any] = {
        "scan_id": str(scan.public_id),
        "domain": scan.domain,
        "verdict": scan.verdict,
        "model_verdict": scan.model_verdict,
        "risk_index": scan.score,
        "source": scan.detection_source,
        "review_url": f"{settings.FRONTEND_URL}/review/{scan.public_id}",
    }
    if review_reason is not None:
        payload["review_reason"] = review_reason
    return payload


def emit_scan_confirmed(scan) -> str | None:
    """scan.confirmed: an analyst saved a CONFIRM_PHISHING decision."""
    return emit_event(SCAN_CONFIRMED, _scan_payload(scan))


def emit_scan_needs_review(scan, *, reason: str) -> str | None:
    """scan.needs_review: uncertain verdict or owner report (never partial)."""
    if scan.partial:
        return None
    return emit_event(
        SCAN_NEEDS_REVIEW, _scan_payload(scan, review_reason=reason)
    )


def send_test_event() -> str | None:
    """Emit one harmless test.event (management command and admin API)."""
    return emit_event(TEST_EVENT, dict(TEST_EVENT_PAYLOAD))


def _webhook_origin() -> str:
    """Scheme + netloc of the fixed webhook base (empty when disabled)."""
    base = (settings.N8N_WEBHOOK_BASE_URL or "").strip().rstrip("/")
    if not base:
        return ""
    parsed = urlparse(base)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""


def webhook_host() -> str:
    """Hostname only: never the scheme, port, path or credentials."""
    return urlparse(settings.N8N_WEBHOOK_BASE_URL or "").hostname or ""


def is_reachable() -> bool:
    """Best-effort GET on n8n /healthz; never raises, 2 s max.

    Only the host fixed in settings is contacted (the base URL is validated
    at startup): no user input ever reaches this call.
    """
    origin = _webhook_origin()
    if not origin:
        return False
    try:
        response = requests.get(
            f"{origin}/healthz", timeout=HEALTH_TIMEOUT_SECONDS
        )
    except requests.RequestException:
        return False
    return response.status_code == 200


def _event_status(action: str) -> str:
    if action == AuditLog.Action.INTEGRATION_DELIVERED:
        return "delivered"
    return "failed"


def get_integration_status() -> dict[str, Any]:
    """Read-only snapshot for the admin automations page.

    Contains no secret and no full webhook URL (hostname only); ``editor_url``
    is the public n8n UI link, never the delivery destination.
    """
    enabled = is_enabled()
    since = timezone.now() - dt.timedelta(hours=24)
    logs = AuditLog.objects.filter(
        action__in=[
            AuditLog.Action.INTEGRATION_DELIVERED,
            AuditLog.Action.INTEGRATION_DELIVERY_FAILED,
        ]
    )
    counts = {"delivered": 0, "failed": 0}
    rows = (
        logs.filter(created_at__gte=since)
        .values("action")
        .annotate(total=Count("id"))
    )
    for row in rows:
        counts[_event_status(row["action"])] = row["total"]

    recent = logs.order_by("-created_at", "-id")[:RECENT_EVENTS_LIMIT]
    return {
        "enabled": enabled,
        "host": webhook_host(),
        "reachable": is_reachable() if enabled else False,
        "editor_url": settings.N8N_EDITOR_URL,
        "events_last_24h": counts,
        "recent_events": [
            {
                "event_type": (log.metadata or {}).get("event_type") or "",
                "status": _event_status(log.action),
                "occurred_at": log.created_at,
            }
            for log in recent
        ],
    }
