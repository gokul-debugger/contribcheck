from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from contribcheck.analyzer import IssueAnalyzer
from contribcheck.api import _bearer_token, app
from contribcheck.models import InspectionReport, IssueTarget, OverallStatus


def _report() -> InspectionReport:
    return InspectionReport(
        target=IssueTarget(owner="owner", repository="repo", number=7),
        title="Ready issue",
        status=OverallStatus.READY,
        checks=[],
        next_actions=["Read the contribution guide."],
    )


async def test_health_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_root_serves_web_interface() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "ContribCheck" in response.text
    assert "/v1/inspect" in response.text
    assert "Authorization" not in response.text


async def test_inspect_endpoint_returns_typed_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_inspect(
        self: IssueAnalyzer, reference: str, *, actor: str | None = None
    ) -> InspectionReport:
        assert reference == "owner/repo#7"
        assert actor == "gokul-debugger"
        return _report()

    monkeypatch.setattr(IssueAnalyzer, "inspect", fake_inspect)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/inspect",
            json={"url": "owner/repo#7", "actor": "gokul-debugger"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["target"]["number"] == 7
    assert response.json()["target"]["url"] == "https://github.com/owner/repo/issues/7"


async def test_inspect_endpoint_rejects_invalid_reference() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/inspect", json={"url": "not-an-issue"})

    assert response.status_code == 400
    assert "HTTP(S) issue URL" in response.json()["detail"]


def test_bearer_token_parser_is_strict() -> None:
    assert _bearer_token("Bearer secret") == "secret"
    assert _bearer_token("bearer secret") == "secret"
    assert _bearer_token("Basic secret") is None
    assert _bearer_token(None) is None
