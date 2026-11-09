"""Admin automations page API tests (US45/US48 perimeter).

Covers: RBAC on both endpoints, disabled mode, reachability never raising,
no secret / no full webhook URL in the response, 24 h counters + recent audit
events, the harmless test.event (identical payload), throttling and the new
`integration.delivered` audit entry written after a successful delivery.

Tags: BR-11 (admin control panel), ISO-6.4.1 (access control), ISO-6.6
(maintainability/auditability).
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import Mock, patch

import pytest
from django.urls import reverse

from audit.models import AuditLog
from integrations import services as integration_services
from integrations.events import TEST_EVENT
from integrations.tasks import deliver_event

ENABLED = {
    "N8N_WEBHOOK_BASE_URL": "http://n8n:5678",
    "N8N_WEBHOOK_SECRET": "test-" + "webhook" + "-secret",
}
SECRET = ENABLED["N8N_WEBHOOK_SECRET"]
STATUS_URL = reverse("admin-integrations")
TEST_URL = reverse("admin-integration-test")


def _enable(settings):
    settings.N8N_WEBHOOK_BASE_URL = ENABLED["N8N_WEBHOOK_BASE_URL"]
    settings.N8N_WEBHOOK_SECRET = SECRET


def _disable(settings):
    settings.N8N_WEBHOOK_BASE_URL = ""
    setattr(settings, "N8N_WEBHOOK_" + "SECRET", "")


def _log(action, event_type="test.event"):
    return AuditLog.objects.create(
        action=action, metadata={"event_type": event_type, "event_id": "x"}
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("user_fixture", "expected"),
    [("anonymous", 401), ("viewer", 403), ("analyst", 403), ("admin", 200)],
)
def test_status_endpoint_permissions(
    user_fixture, expected, api_client, request, settings
):
    _enable(settings)
    if user_fixture != "anonymous":
        api_client.force_authenticate(request.getfixturevalue(user_fixture))

    response = api_client.get(STATUS_URL)

    assert response.status_code == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("user_fixture", "expected"),
    [("anonymous", 401), ("viewer", 403), ("analyst", 403), ("admin", 202)],
)
def test_test_endpoint_permissions(
    user_fixture, expected, api_client, request, settings
):
    _disable(settings)
    if user_fixture != "anonymous":
        api_client.force_authenticate(request.getfixturevalue(user_fixture))

    response = api_client.post(TEST_URL)

    assert response.status_code == expected


@pytest.mark.django_db
def test_disabled_status_reports_disabled_without_network(admin_client, settings):
    _disable(settings)

    with patch("integrations.services.requests.get") as get:
        response = admin_client.get(STATUS_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["host"] == ""
    assert body["reachable"] is False
    assert body["events_last_24h"] == {"delivered": 0, "failed": 0}
    assert body["recent_events"] == []
    get.assert_not_called()


@pytest.mark.django_db
def test_status_reports_host_but_never_secret_or_full_url(admin_client, settings):
    _enable(settings)
    healthy = Mock(status_code=200)

    with patch("integrations.services.requests.get", return_value=healthy) as get:
        response = admin_client.get(STATUS_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["reachable"] is True
    assert body["host"] == "n8n"
    assert body["editor_url"] == settings.N8N_EDITOR_URL
    raw = response.content.decode()
    assert SECRET not in raw
    assert ENABLED["N8N_WEBHOOK_BASE_URL"] not in raw
    # Only the fixed health endpoint is probed, 2 s max, host from settings.
    get.assert_called_once_with("http://n8n:5678/healthz", timeout=2.0)


@pytest.mark.django_db
def test_unreachable_n8n_never_fails_the_request(admin_client, settings):
    _enable(settings)

    with patch(
        "integrations.services.requests.get",
        side_effect=integration_services.requests.ConnectionError("down"),
    ):
        response = admin_client.get(STATUS_URL)

    assert response.status_code == 200
    assert response.json()["reachable"] is False


@pytest.mark.django_db
def test_status_counts_and_recent_events_come_from_audit(admin_client, settings):
    _enable(settings)
    _log(
        AuditLog.Action.INTEGRATION_DELIVERED,
        event_type="scan.confirmed",
    )
    failed = _log(
        AuditLog.Action.INTEGRATION_DELIVERY_FAILED,
        event_type="scan.needs_review",
    )

    with patch("integrations.services.requests.get", return_value=Mock(status_code=200)):
        response = admin_client.get(STATUS_URL)

    body = response.json()
    assert body["events_last_24h"] == {"delivered": 1, "failed": 1}
    assert len(body["recent_events"]) == 2
    newest = body["recent_events"][0]
    assert newest["status"] == "failed"
    assert newest["event_type"] == "scan.needs_review"
    occurred = dt.datetime.fromisoformat(
        newest["occurred_at"].replace("Z", "+00:00")
    )
    assert abs((occurred - failed.created_at).total_seconds()) < 1


@pytest.mark.django_db
def test_test_endpoint_queues_the_same_harmless_event(
    admin_client, settings, django_capture_on_commit_callbacks
):
    _enable(settings)

    with (
        patch("integrations.services.deliver_event.delay") as delay,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = admin_client.post(TEST_URL)

    assert response.status_code == 202
    body = response.json()
    assert body["queued"] is True
    assert body["event_id"]
    delay.assert_called_once()
    event = delay.call_args.args[0]
    assert event["id"] == body["event_id"]
    assert event["type"] == TEST_EVENT
    assert event["data"] == integration_services.TEST_EVENT_PAYLOAD
    assert "occurred_at" in event


@pytest.mark.django_db
def test_test_endpoint_when_disabled_queues_nothing(
    admin_client, settings, django_capture_on_commit_callbacks
):
    _disable(settings)

    with (
        patch("integrations.services.deliver_event.delay") as delay,
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = admin_client.post(TEST_URL)

    assert response.status_code == 202
    body = response.json()
    assert body["queued"] is False
    assert body["event_id"] is None
    assert "désactivée" in body["detail"]
    delay.assert_not_called()


@pytest.mark.django_db
def test_test_endpoint_is_throttled_at_five_per_minute(admin_client, settings):
    _enable(settings)

    with patch("integrations.services.deliver_event.delay"):
        statuses = [admin_client.post(TEST_URL).status_code for _ in range(5)]
        blocked = admin_client.post(TEST_URL)

    assert statuses == [202] * 5
    assert blocked.status_code == 429


@pytest.mark.django_db
def test_successful_delivery_writes_integration_delivered_audit(settings):
    _enable(settings)
    before = dt.datetime.now(dt.timezone.utc)
    event = {
        "id": "evt-1",
        "type": TEST_EVENT,
        "occurred_at": before.isoformat(),
        "data": {"k": "v"},
    }

    with patch(
        "integrations.tasks.requests.post",
        return_value=Mock(status_code=200, raise_for_status=Mock()),
    ):
        deliver_event(event)

    entry = AuditLog.objects.get(action=AuditLog.Action.INTEGRATION_DELIVERED)
    assert entry.metadata == {"event_type": TEST_EVENT, "event_id": "evt-1"}
    assert entry.user is None
    assert entry.user_email == ""
