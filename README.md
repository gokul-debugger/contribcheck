# ContribCheck: GitHub Issue Readiness Checker

An evidence-based CLI and API that checks whether a GitHub issue is genuinely ready for an open-source contribution.

[![CI](https://github.com/gokul-debugger/contribcheck/actions/workflows/ci.yml/badge.svg)](https://github.com/gokul-debugger/contribcheck/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

ContribCheck identifies blockers that issue-discovery lists often miss: dependency issues, missing base branches, existing assignments, comment claims, competing pull requests, unhealthy default-branch CI, and missing contribution guidance.

It does not predict whether a maintainer will merge a pull request. Every result is linked to observable GitHub state, and signals that cannot be verified are reported as `unknown` instead of silently passing.

## Real-World Example

Two open issues from the same repository can look equally available while having very different readiness states.

### Blocked by a prerequisite

```bash
contribcheck inspect https://github.com/sigma67/ytmusicapi/issues/986 \
  --actor gokul-debugger
```

```text
Lyrics models
https://github.com/sigma67/ytmusicapi/issues/986
Verdict: BLOCKED

FAILURE  Dependencies        Blocked by 1 open issue(s).
FAILURE  Base branch         Required branch `ytmusicapi-2` does not exist.
PASS     Assignment          Assigned to the requested contributor.
PASS     Competing PRs       No open pull request referencing this issue was found.

Next actions
- Wait for the listed dependency issues to close.
- Ask the maintainer to create or clarify the required base branch.
- Read the repository contribution guide before creating a branch.
```

ContribCheck prevents work from starting too early: the contributor is assigned, but the required dependency and base branch are not ready.

### Ready for contribution

```bash
contribcheck inspect https://github.com/sigma67/ytmusicapi/issues/941
```

```text
get_song() can return stale likeStatus right after rate_song()
https://github.com/sigma67/ytmusicapi/issues/941
Verdict: READY

PASS  Dependencies        No open blockers reported.
PASS  Assignment          The issue is unassigned.
PASS  Comment claims      No other contributor appears to have claimed it.
PASS  Competing PRs       No open pull request referencing this issue was found.
PASS  Default branch CI   Latest runs for 4 workflow(s) are green.
PASS  Maintainer response A maintainer first replied after approximately 8 hours.

Next actions
- Read the repository contribution guide before creating a branch.
- Comment with a concise implementation plan before starting work.
```

Here the evidence supports beginning the contribution workflow, while still recommending coordination with the maintainer.

## Why It Exists

Labels such as `good first issue` and `help wanted` are useful discovery signals, but they do not guarantee that an issue is actionable. A contribution can still be blocked by another issue, depend on a branch that has not been created, overlap an existing pull request, or wait in a repository whose default CI is already failing.

ContribCheck performs that second-stage verification before a contributor invests hours in setup and implementation.

## Checks

| Check | Evidence | Effect |
|---|---|---|
| Issue state | GitHub issue state | Closed issues block work |
| Dependencies | GitHub issue dependency API | Open dependencies block work |
| Base branch | Explicit branch named in the issue body | A missing required branch blocks work |
| Assignment | Current assignees | Another assignee blocks uncoordinated work |
| Comment claims | Explicit work-claim phrases | Produces a caution |
| Competing PRs | Timeline cross-references and PR search | Produces a caution |
| Scope | Issue body and acceptance-language markers | Warns when clarification may be needed |
| Contribution guide | Repository tree | Warns when standard guidance is absent |
| Repository health | Archive status and recent push activity | Blocks archived repositories, warns on inactivity |
| Default CI | Latest completed workflow run per workflow | Warns about pre-existing failures |
| Maintainer response | Comment author association and timestamps | Reports issue-level responsiveness |

The overall result is one of:

- `ready`: no blocking, warning, or unknown signals were found
- `caution`: manual review is needed
- `blocked`: a hard prerequisite is not satisfied

## Installation

ContribCheck requires Python 3.11 or newer.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Public GitHub requests work without authentication, but GitHub applies a much smaller anonymous rate limit. Set a token for regular use:

```bash
export GITHUB_TOKEN="your-fine-grained-token"
```

Read-only access to public metadata is sufficient. Do not grant write permissions.

## CLI

Inspect by URL:

```bash
contribcheck inspect https://github.com/owner/repository/issues/123
```

Inspect by shorthand and emit JSON:

```bash
contribcheck inspect owner/repository#123 --actor your-username --json
```

Use the result in CI or a script:

```bash
contribcheck inspect owner/repository#123 --fail-on caution
```

Exit codes are `0` for a completed inspection, `1` for an operational error, and `2` when the configured readiness threshold is reached.

### GitHub Enterprise Server

Set the API endpoint with `GITHUB_API_URL`, or override it for one command with `--base-url`:

```bash
export GITHUB_API_URL="https://github.example.com/api/v3"
contribcheck inspect https://github.example.com/team/project/issues/123
contribcheck inspect team/project#123 --base-url https://github.example.com/api/v3
```

The precedence is CLI option, `GITHUB_API_URL`, then `https://api.github.com`. The endpoint must be HTTP or HTTPS and cannot contain credentials, query parameters, or fragments. Tokens are sent only to the configured API endpoint.

## Python SDK

```python
import asyncio

from contribcheck import GitHubClient, IssueAnalyzer


async def main() -> None:
    async with GitHubClient() as client:
        report = await IssueAnalyzer(client).inspect(
            "https://github.com/sigma67/ytmusicapi/issues/986",
            actor="gokul-debugger",
        )
    print(report.status)
    print(report.check("dependencies").summary)


asyncio.run(main())
```

## HTTP API

Install server dependencies and start FastAPI:

```bash
pip install -e '.[server]'
contribcheck serve
```

Open `http://127.0.0.1:8000/docs`, or call the API directly:

```bash
curl -X POST http://127.0.0.1:8000/v1/inspect \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://github.com/sigma67/ytmusicapi/issues/986",
    "actor": "gokul-debugger"
  }'
```

The service accepts an optional `Authorization: Bearer ...` header. It never stores the token.

## Docker

```bash
docker build -t contribcheck .
docker run --rm -p 8000:8000 -e GITHUB_TOKEN contribcheck
```

## Development

This repository uses `uv` for reproducible development environments:

```bash
uv sync --all-extras --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov=contribcheck --cov-report=term-missing
```

Tests use a mocked GitHub transport and do not consume API quota.

## Contributing

Contributions are welcome. Start with the [good first issues](https://github.com/gokul-debugger/contribcheck/issues?q=is%3Aissue%20state%3Aopen%20label%3A%22good%20first%20issue%22) or browse tasks marked [help wanted](https://github.com/gokul-debugger/contribcheck/issues?q=is%3Aissue%20state%3Aopen%20label%3A%22help%20wanted%22).

Read [CONTRIBUTING.md](CONTRIBUTING.md), comment with a short implementation plan, and wait for confirmation before starting work that changes a public contract.

## Current Limitations

- Comment-claim detection is conservative text matching, not proof of ownership.
- Competing PR detection can miss work that never references the issue.
- Maintainer responsiveness is measured only on the inspected issue in this release.
- Explicit base-branch detection depends on recognizable wording in the issue body.
- Private repositories require a token with appropriate read access.
- GitHub remains the source of truth; always review linked evidence before acting.

## Roadmap

- Repository-wide maintainer response statistics
- Local clone and development-environment readiness checks
- GitHub App checks embedded directly in issue conversations
- Browser extension for one-click inspection
- Configurable organization policies and output formats

## License

MIT
