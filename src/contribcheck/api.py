"""Optional FastAPI application exposing the inspection engine."""

from __future__ import annotations

import os
from typing import Annotated

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import RedirectResponse

from contribcheck import __version__
from contribcheck.analyzer import IssueAnalyzer
from contribcheck.exceptions import ContribCheckError, GitHubRateLimitError
from contribcheck.github import GitHubClient
from contribcheck.models import InspectionReport, InspectionRequest

app = FastAPI(
    title="ContribCheck API",
    version=__version__,
    description="Evidence-based preflight checks for open-source GitHub issues.",
)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Send browser users directly to the interactive API documentation."""

    return RedirectResponse(url="/docs")


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a dependency-free process health response."""

    return {"status": "ok", "version": __version__}


@app.post("/v1/inspect", response_model=InspectionReport)
async def inspect_issue(
    request: InspectionRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> InspectionReport:
    """Inspect a GitHub issue using a server or caller-provided token."""

    token = _bearer_token(authorization) or os.getenv("GITHUB_TOKEN")
    try:
        async with GitHubClient(token=token) as client:
            return await IssueAnalyzer(client).inspect(request.url, actor=request.actor)
    except GitHubRateLimitError as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    except (ContribCheckError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=f"GitHub request failed: {error}") from error


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator and scheme.casefold() == "bearer" and token:
        return token
    return None
