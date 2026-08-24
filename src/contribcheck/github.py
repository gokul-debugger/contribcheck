"""Small async GitHub REST client tailored to readiness inspection."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import Any, Self, cast
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from contribcheck.exceptions import GitHubAPIError, GitHubRateLimitError
from contribcheck.models import IssueTarget, JsonObject

API_VERSION = "2026-03-10"
DEFAULT_API_URL = "https://api.github.com"
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


class GitHubClient:
    """Read-only client for the GitHub endpoints used by ContribCheck."""

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 15.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        resolved_token = token if token is not None else os.getenv("GITHUB_TOKEN")
        resolved_base_url = normalize_api_base_url(
            base_url if base_url is not None else os.getenv("GITHUB_API_URL")
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "contribcheck/0.1.0",
            "X-GitHub-Api-Version": API_VERSION,
        }
        if resolved_token:
            headers["Authorization"] = f"Bearer {resolved_token}"

        self._client = httpx.AsyncClient(
            base_url=resolved_base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )
        self._max_retries = max_retries
        self.request_count = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""

        await self._client.aclose()

    async def get_repository(self, target: IssueTarget) -> JsonObject:
        """Fetch repository metadata."""

        return self._expect_object(await self._get(f"/repos/{target.full_name}"))

    async def get_issue(self, target: IssueTarget) -> JsonObject:
        """Fetch one issue."""

        return self._expect_object(
            await self._get(f"/repos/{target.full_name}/issues/{target.number}")
        )

    async def get_blocking_dependencies(self, target: IssueTarget) -> list[JsonObject]:
        """List issues that block the target issue."""

        data = await self._get(
            f"/repos/{target.full_name}/issues/{target.number}/dependencies/blocked_by",
            params={"per_page": 100},
        )
        return self._expect_object_list(data)

    async def get_comments(self, target: IssueTarget) -> list[JsonObject]:
        """Fetch up to 300 issue comments."""

        return await self._get_paginated(
            f"/repos/{target.full_name}/issues/{target.number}/comments"
        )

    async def get_timeline(self, target: IssueTarget) -> list[JsonObject]:
        """Fetch up to 300 issue timeline events."""

        return await self._get_paginated(
            f"/repos/{target.full_name}/issues/{target.number}/timeline"
        )

    async def branch_exists(self, target: IssueTarget, branch: str) -> bool:
        """Return whether a branch exists, propagating non-404 failures."""

        endpoint = f"/repos/{target.full_name}/branches/{quote(branch, safe='')}"
        try:
            await self._get(endpoint)
        except GitHubAPIError as error:
            if error.status_code == 404:
                return False
            raise
        return True

    async def get_tree_paths(self, target: IssueTarget, ref: str) -> set[str]:
        """Return repository paths from a recursive Git tree response."""

        data = self._expect_object(
            await self._get(
                f"/repos/{target.full_name}/git/trees/{quote(ref, safe='')}",
                params={"recursive": 1},
            )
        )
        tree = data.get("tree", [])
        if not isinstance(tree, list):
            raise GitHubAPIError(502, "Malformed tree response", endpoint="git/trees")
        return {
            entry["path"]
            for entry in tree
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        }

    async def get_recent_workflow_runs(
        self, target: IssueTarget, branch: str, *, limit: int = 10
    ) -> list[JsonObject]:
        """Return recent completed Actions runs for a branch."""

        data = self._expect_object(
            await self._get(
                f"/repos/{target.full_name}/actions/runs",
                params={"branch": branch, "status": "completed", "per_page": limit},
            )
        )
        runs = data.get("workflow_runs", [])
        if not isinstance(runs, list):
            raise GitHubAPIError(502, "Malformed workflow run response", endpoint="actions/runs")
        return [cast(JsonObject, run) for run in runs if isinstance(run, dict)]

    async def search_open_pull_requests(self, target: IssueTarget) -> list[JsonObject]:
        """Find open PR bodies that explicitly mention the target issue number."""

        query = f'repo:{target.full_name} is:pr is:open "#{target.number}" in:body'
        data = self._expect_object(
            await self._get("/search/issues", params={"q": query, "per_page": 100})
        )
        items = data.get("items", [])
        if not isinstance(items, list):
            raise GitHubAPIError(502, "Malformed search response", endpoint="search/issues")
        return [cast(JsonObject, item) for item in items if isinstance(item, dict)]

    async def _get_paginated(self, endpoint: str, *, max_pages: int = 3) -> list[JsonObject]:
        results: list[JsonObject] = []
        per_page = 100
        for page in range(1, max_pages + 1):
            data = await self._get(endpoint, params={"per_page": per_page, "page": page})
            current = self._expect_object_list(data)
            results.extend(current)
            if len(current) < per_page:
                break
        return results

    async def _get(self, endpoint: str, *, params: Mapping[str, str | int] | None = None) -> Any:
        response: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            self.request_count += 1
            try:
                response = await self._client.get(endpoint, params=params)
            except httpx.RequestError:
                if attempt == self._max_retries:
                    raise
                await asyncio.sleep(0.25 * (2**attempt))
                continue

            if response.status_code not in TRANSIENT_STATUSES or attempt == self._max_retries:
                break

            retry_after = response.headers.get("Retry-After")
            delay = min(float(retry_after), 2.0) if retry_after else 0.25 * (2**attempt)
            await asyncio.sleep(delay)

        if response is None:
            raise RuntimeError("GitHub request loop finished without a response")

        if response.is_success:
            return response.json()

        message = self._error_message(response)
        if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            raise GitHubRateLimitError(response.status_code, message, endpoint=endpoint)
        raise GitHubAPIError(response.status_code, message, endpoint=endpoint)

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text or response.reason_phrase
        if isinstance(payload, dict) and isinstance(payload.get("message"), str):
            return cast(str, payload["message"])
        return response.reason_phrase

    @staticmethod
    def _expect_object(value: Any) -> JsonObject:
        if not isinstance(value, dict):
            raise GitHubAPIError(502, "Expected a JSON object", endpoint="response")
        return cast(JsonObject, value)

    @staticmethod
    def _expect_object_list(value: Any) -> list[JsonObject]:
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise GitHubAPIError(502, "Expected a list of JSON objects", endpoint="response")
        return cast(list[JsonObject], value)


def normalize_api_base_url(value: str | None) -> str:
    """Validate and normalize a GitHub API endpoint."""

    candidate = (value or DEFAULT_API_URL).strip()
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "GitHub API URL must be an HTTP(S) URL without credentials, query parameters, "
            "or fragments."
        )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
