from __future__ import annotations

import json

import httpx
import pytest

from contribcheck.exceptions import GitHubRateLimitError
from contribcheck.github import API_VERSION, GitHubClient, normalize_api_base_url
from contribcheck.models import IssueTarget

TARGET = IssueTarget(owner="owner", repository="repo", number=7)


@pytest.mark.asyncio
async def test_client_sends_version_and_authentication_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-GitHub-Api-Version"] == API_VERSION
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json={"default_branch": "main"})

    async with GitHubClient(token="secret", transport=httpx.MockTransport(handler)) as client:
        repository = await client.get_repository(TARGET)

    assert repository["default_branch"] == "main"


@pytest.mark.asyncio
async def test_explicit_api_url_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_API_URL", "https://env.example/api/v3")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://explicit.example/api/v3/")
        return httpx.Response(200, json={"default_branch": "main"})

    async with GitHubClient(
        base_url="https://explicit.example/api/v3/",
        transport=httpx.MockTransport(handler),
    ) as client:
        await client.get_repository(TARGET)


def test_normalize_api_base_url_rejects_credentials_and_query() -> None:
    assert (
        normalize_api_base_url("https://github.example/api/v3/") == "https://github.example/api/v3"
    )
    with pytest.raises(ValueError):
        normalize_api_base_url("https://user:secret@github.example/api/v3")
    with pytest.raises(ValueError):
        normalize_api_base_url("https://github.example/api/v3?token=secret")


@pytest.mark.asyncio
async def test_branch_exists_returns_false_for_404() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(404, json={"message": "Not Found"}))

    async with GitHubClient(transport=transport) as client:
        exists = await client.branch_exists(TARGET, "missing")

    assert exists is False


@pytest.mark.asyncio
async def test_rate_limit_has_specific_error() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0"},
            json={"message": "API rate limit exceeded"},
        )
    )

    async with GitHubClient(transport=transport) as client:
        with pytest.raises(GitHubRateLimitError):
            await client.get_issue(TARGET)


@pytest.mark.asyncio
async def test_transient_failure_is_retried() -> None:
    responses = iter(
        [
            httpx.Response(503, json={"message": "Unavailable"}),
            httpx.Response(200, content=json.dumps({"title": "Ready"}).encode()),
        ]
    )
    transport = httpx.MockTransport(lambda _: next(responses))

    async with GitHubClient(transport=transport) as client:
        issue = await client.get_issue(TARGET)

        assert client.request_count == 2
    assert issue["title"] == "Ready"
