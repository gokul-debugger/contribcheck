"""Optional FastAPI application exposing the inspection engine."""

from __future__ import annotations

import os
from typing import Annotated

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse

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

WEB_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ContribCheck</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { margin: 0; background: #101827; color: #e5edf7; }
    main { width: min(960px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0; }
    h1 { margin-bottom: 8px; }
    .muted { color: #a8b5c7; }
    form, .panel {
      background: #172235; border: 1px solid #2b3b54; border-radius: 8px; padding: 20px;
    }
    form { display: grid; gap: 14px; margin: 28px 0; }
    label { display: grid; gap: 6px; font-weight: 650; }
    input {
      border: 1px solid #4a607e; border-radius: 6px; padding: 11px 12px;
      background: #0e1726; color: inherit; font: inherit;
    }
    button {
      width: fit-content; border: 0; border-radius: 6px; padding: 11px 18px;
      background: #4f8cff; color: white; font: inherit; font-weight: 700; cursor: pointer;
    }
    button:disabled { cursor: wait; opacity: .65; }
    .status { min-height: 24px; }
    .verdict {
      display: inline-block; border-radius: 999px; padding: 5px 10px;
      font-weight: 800;
    }
    .ready { background: #14532d; color: #bbf7d0; }
    .caution { background: #713f12; color: #fef3c7; }
    .blocked { background: #7f1d1d; color: #fecaca; }
    .failure { color: #fca5a5; }
    .warning { color: #fcd34d; }
    .unknown { color: #d8b4fe; }
    table { width: 100%; border-collapse: collapse; margin-top: 16px; }
    th, td {
      text-align: left; vertical-align: top; border-bottom: 1px solid #2b3b54;
      padding: 10px 8px;
    }
    th { color: #b9c8dc; }
    a { color: #8db8ff; }
    ul { padding-left: 22px; }
    @media (max-width: 640px) {
      main { padding: 24px 0; }
      th:nth-child(1), td:nth-child(1) { display: none; }
    }
  </style>
</head>
<body>
  <main>
    <h1>ContribCheck</h1>
    <p class="muted">Evidence-based preflight checks for open-source GitHub issues.</p>
    <form id="inspect-form">
      <label for="reference">Issue reference
        <input id="reference" name="reference" required
               placeholder="owner/repository#123 or issue URL">
      </label>
      <label for="actor">GitHub username <span class="muted">(optional)</span>
        <input id="actor" name="actor" placeholder="your-username" autocomplete="off">
      </label>
      <button id="submit" type="submit">Inspect issue</button>
      <div id="status" class="status muted" role="status" aria-live="polite"></div>
    </form>
    <section id="result" class="panel" hidden aria-live="polite"></section>
  </main>
  <script>
    const form = document.querySelector("#inspect-form");
    const button = document.querySelector("#submit");
    const status = document.querySelector("#status");
    const result = document.querySelector("#result");

    function text(tag, value, className) {
      const node = document.createElement(tag);
      node.textContent = value;
      if (className) node.className = className;
      return node;
    }

    function renderReport(report) {
      result.replaceChildren();
      const heading = text("h2", report.title);
      const issueLink = document.createElement("a");
      issueLink.href = report.target.url;
      issueLink.textContent = report.target.url;
      issueLink.target = "_blank";
      issueLink.rel = "noreferrer";
      result.append(heading, issueLink);
      result.append(text("p", "Verdict: ", "muted"));
      result.lastChild.append(
        text("span", report.status.toUpperCase(), `verdict ${report.status}`)
      );

      const table = document.createElement("table");
      table.innerHTML = "<thead><tr><th>Status</th><th>Check</th><th>Finding</th></tr></thead>";
      const body = document.createElement("tbody");
      for (const check of report.checks) {
        const row = document.createElement("tr");
        row.append(text("td", check.status.toUpperCase(), check.status));
        row.append(text("td", check.title));
        const finding = document.createElement("td");
        finding.append(text("div", check.summary));
        for (const evidence of check.evidence) {
          const item = document.createElement("div");
          if (evidence.url) {
            const link = document.createElement("a");
            link.href = evidence.url;
            link.textContent = evidence.text;
            link.target = "_blank";
            link.rel = "noreferrer";
            item.append(link);
          } else {
            item.append(text("span", evidence.text));
          }
          finding.append(item);
        }
        row.append(finding);
        body.append(row);
      }
      table.append(body);
      result.append(table, text("h3", "Next actions"));
      const actions = document.createElement("ul");
      for (const action of report.next_actions) actions.append(text("li", action));
      result.append(actions);
      result.hidden = false;
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      button.disabled = true;
      result.hidden = true;
      status.className = "status muted";
      status.textContent = "Inspecting issue...";
      const payload = {
        url: document.querySelector("#reference").value.trim(),
        actor: document.querySelector("#actor").value.trim() || null,
      };
      try {
        const response = await fetch("/v1/inspect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Inspection failed.");
        renderReport(data);
        status.textContent = "Inspection complete.";
      } catch (error) {
        status.textContent = error instanceof Error ? error.message : "Inspection failed.";
        status.className = "status failure";
      } finally {
        button.disabled = false;
      }
    });
  </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root() -> HTMLResponse:
    """Serve the lightweight browser inspection interface."""

    return HTMLResponse(WEB_PAGE)


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
