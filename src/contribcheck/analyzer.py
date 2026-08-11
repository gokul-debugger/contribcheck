"""Deterministic readiness analysis built from public GitHub evidence."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Generic, Protocol, TypeVar, cast

from pydantic import HttpUrl

from contribcheck.models import (
    CheckResult,
    Evidence,
    InspectionReport,
    IssueTarget,
    JsonObject,
    OverallStatus,
    SignalStatus,
)
from contribcheck.parsing import comment_claims_work, extract_base_branch, parse_issue_reference

T = TypeVar("T")
MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
HARD_BLOCKER_KEYS = {"issue_state", "dependencies", "base_branch", "assignment", "repository"}


@dataclass(frozen=True)
class FetchResult(Generic[T]):
    """Value-or-error wrapper used to keep optional checks independent."""

    value: T | None = None
    error: Exception | None = None


async def _capture(awaitable: Awaitable[T]) -> FetchResult[T]:
    try:
        return FetchResult(value=await awaitable)
    except Exception as error:  # Optional signals must not turn into false readiness.
        return FetchResult(error=error)


class GitHubReader(Protocol):
    """Read operations required by the analyzer."""

    async def get_repository(self, target: IssueTarget) -> JsonObject: ...

    async def get_issue(self, target: IssueTarget) -> JsonObject: ...

    async def get_blocking_dependencies(self, target: IssueTarget) -> list[JsonObject]: ...

    async def get_comments(self, target: IssueTarget) -> list[JsonObject]: ...

    async def get_timeline(self, target: IssueTarget) -> list[JsonObject]: ...

    async def search_open_pull_requests(self, target: IssueTarget) -> list[JsonObject]: ...

    async def get_tree_paths(self, target: IssueTarget, ref: str) -> set[str]: ...

    async def get_recent_workflow_runs(
        self, target: IssueTarget, branch: str, *, limit: int = 10
    ) -> list[JsonObject]: ...

    async def branch_exists(self, target: IssueTarget, branch: str) -> bool: ...


class IssueAnalyzer:
    """Inspect whether a public GitHub issue is ready for contribution."""

    def __init__(self, client: GitHubReader) -> None:
        self.client = client

    async def inspect(self, reference: str, *, actor: str | None = None) -> InspectionReport:
        """Build a report for one issue URL or shorthand reference."""

        target = parse_issue_reference(reference)
        repository, issue = await asyncio.gather(
            self.client.get_repository(target), self.client.get_issue(target)
        )
        if "pull_request" in issue:
            raise ValueError("ContribCheck currently inspects issues, not pull requests.")

        default_branch = _string(repository.get("default_branch")) or "main"
        base_branch = extract_base_branch(_string(issue.get("body")))

        (
            dependencies_result,
            comments_result,
            timeline_result,
            search_result,
            tree_result,
            runs_result,
        ) = await asyncio.gather(
            _capture(self.client.get_blocking_dependencies(target)),
            _capture(self.client.get_comments(target)),
            _capture(self.client.get_timeline(target)),
            _capture(self.client.search_open_pull_requests(target)),
            _capture(self.client.get_tree_paths(target, default_branch)),
            _capture(self.client.get_recent_workflow_runs(target, default_branch)),
        )
        branch_result = (
            await _capture(self.client.branch_exists(target, base_branch))
            if base_branch
            else FetchResult[bool](value=None)
        )

        checks = [
            self._issue_state_check(issue),
            self._dependency_check(dependencies_result),
            self._base_branch_check(base_branch, branch_result, target),
            self._assignment_check(issue, actor),
            self._claims_check(comments_result, actor),
            self._competing_pr_check(timeline_result, search_result),
            self._scope_check(issue),
            self._contribution_docs_check(tree_result, target, default_branch),
            self._repository_check(repository),
            self._ci_check(runs_result),
            self._maintainer_response_check(issue, comments_result),
        ]
        status = self._overall_status(checks)
        return InspectionReport(
            target=target,
            title=_string(issue.get("title")) or f"Issue #{target.number}",
            status=status,
            checks=checks,
            next_actions=self._next_actions(checks, status),
        )

    @staticmethod
    def _issue_state_check(issue: JsonObject) -> CheckResult:
        state = (_string(issue.get("state")) or "unknown").casefold()
        if state == "open":
            return _check("issue_state", "Issue state", SignalStatus.PASS, "The issue is open.")
        return _check(
            "issue_state",
            "Issue state",
            SignalStatus.FAILURE,
            f"The issue is {state}; new implementation work should not begin.",
        )

    @staticmethod
    def _dependency_check(result: FetchResult[list[JsonObject]]) -> CheckResult:
        if result.error:
            return _unknown("dependencies", "Dependencies", result.error)
        dependencies = result.value or []
        open_dependencies = [item for item in dependencies if item.get("state") == "open"]
        if not open_dependencies:
            return _check(
                "dependencies", "Dependencies", SignalStatus.PASS, "No open blockers reported."
            )
        evidence = [
            Evidence(
                text=f"#{item.get('number')}: {item.get('title', 'Untitled issue')}",
                url=_url(item.get("html_url")),
            )
            for item in open_dependencies
        ]
        return _check(
            "dependencies",
            "Dependencies",
            SignalStatus.FAILURE,
            f"Blocked by {len(open_dependencies)} open issue(s).",
            evidence,
        )

    @staticmethod
    def _base_branch_check(
        branch: str | None, result: FetchResult[bool], target: IssueTarget
    ) -> CheckResult:
        if branch is None:
            return _check(
                "base_branch",
                "Base branch",
                SignalStatus.INFO,
                "No non-default base branch is explicitly required in the issue body.",
            )
        if result.error:
            return _unknown("base_branch", "Base branch", result.error)
        if result.value:
            return _check(
                "base_branch",
                "Base branch",
                SignalStatus.PASS,
                f"Required branch `{branch}` exists.",
                [
                    Evidence(
                        text=branch,
                        url=_url(f"https://github.com/{target.full_name}/tree/{branch}"),
                    )
                ],
            )
        return _check(
            "base_branch",
            "Base branch",
            SignalStatus.FAILURE,
            f"Required branch `{branch}` does not exist.",
        )

    @staticmethod
    def _assignment_check(issue: JsonObject, actor: str | None) -> CheckResult:
        assignees = _logins(issue.get("assignees"))
        if not assignees:
            return _check("assignment", "Assignment", SignalStatus.PASS, "The issue is unassigned.")
        if actor and actor.casefold() in {login.casefold() for login in assignees}:
            return _check(
                "assignment",
                "Assignment",
                SignalStatus.PASS,
                f"Assigned to the requested contributor, `{actor}`.",
            )
        return _check(
            "assignment",
            "Assignment",
            SignalStatus.FAILURE,
            "The issue is already assigned.",
            [Evidence(text=login, url=_url(f"https://github.com/{login}")) for login in assignees],
        )

    @staticmethod
    def _claims_check(result: FetchResult[list[JsonObject]], actor: str | None) -> CheckResult:
        if result.error:
            return _unknown("claims", "Comment claims", result.error)
        claims: dict[str, JsonObject] = {}
        for comment in result.value or []:
            body = _string(comment.get("body")) or ""
            login = _nested_string(comment, "user", "login")
            if not login or login.endswith("[bot]") or not comment_claims_work(body):
                continue
            if actor and login.casefold() == actor.casefold():
                continue
            claims.setdefault(login, comment)
        if not claims:
            return _check(
                "claims",
                "Comment claims",
                SignalStatus.PASS,
                "No other contributor appears to have claimed the issue in comments.",
            )
        evidence = [
            Evidence(text=login, url=_url(comment.get("html_url")))
            for login, comment in claims.items()
        ]
        return _check(
            "claims",
            "Comment claims",
            SignalStatus.WARNING,
            "Another contributor may already be working on this issue.",
            evidence,
        )

    @staticmethod
    def _competing_pr_check(
        timeline_result: FetchResult[list[JsonObject]],
        search_result: FetchResult[list[JsonObject]],
    ) -> CheckResult:
        pull_requests: dict[str, str] = {}
        for event in timeline_result.value or []:
            if event.get("event") != "cross-referenced":
                continue
            source_issue = _nested_object(event, "source", "issue")
            if not source_issue or "pull_request" not in source_issue:
                continue
            if source_issue.get("state") != "open":
                continue
            url = _string(source_issue.get("html_url"))
            if url:
                pull_requests[url] = _string(source_issue.get("title")) or url
        for item in search_result.value or []:
            url = _string(item.get("html_url"))
            if url:
                pull_requests[url] = _string(item.get("title")) or url

        partial_error = timeline_result.error or search_result.error
        if not pull_requests:
            if partial_error:
                return _unknown("competing_prs", "Competing pull requests", partial_error)
            return _check(
                "competing_prs",
                "Competing pull requests",
                SignalStatus.PASS,
                "No open pull request referencing this issue was found.",
            )
        return _check(
            "competing_prs",
            "Competing pull requests",
            SignalStatus.WARNING,
            f"Found {len(pull_requests)} potentially competing open PR(s).",
            [Evidence(text=title, url=_url(url)) for url, title in pull_requests.items()],
        )

    @staticmethod
    def _scope_check(issue: JsonObject) -> CheckResult:
        body = (_string(issue.get("body")) or "").strip()
        normalized = body.casefold()
        has_outcome = any(
            marker in normalized
            for marker in (
                "definition of done",
                "acceptance criteria",
                "expected behavior",
                "scope",
            )
        )
        if len(body) >= 200 and has_outcome:
            return _check(
                "scope", "Issue scope", SignalStatus.PASS, "The issue describes scope or outcomes."
            )
        if len(body) >= 100:
            return _check(
                "scope",
                "Issue scope",
                SignalStatus.INFO,
                "The issue has context, but acceptance criteria are not explicit.",
            )
        return _check(
            "scope",
            "Issue scope",
            SignalStatus.WARNING,
            "The issue description may be too brief to implement safely without clarification.",
        )

    @staticmethod
    def _contribution_docs_check(
        result: FetchResult[set[str]], target: IssueTarget, default_branch: str
    ) -> CheckResult:
        if result.error:
            return _unknown("contribution_docs", "Contribution guide", result.error)
        paths = result.value or set()
        candidates = sorted(
            path
            for path in paths
            if path.casefold() in {"contributing.md", "contributing.rst", ".github/contributing.md"}
        )
        if not candidates:
            return _check(
                "contribution_docs",
                "Contribution guide",
                SignalStatus.WARNING,
                "No standard contribution guide was found.",
            )
        path = candidates[0]
        return _check(
            "contribution_docs",
            "Contribution guide",
            SignalStatus.PASS,
            f"Found `{path}`.",
            [
                Evidence(
                    text=path,
                    url=_url(f"https://github.com/{target.full_name}/blob/{default_branch}/{path}"),
                )
            ],
        )

    @staticmethod
    def _repository_check(repository: JsonObject) -> CheckResult:
        if repository.get("archived") is True or repository.get("disabled") is True:
            return _check(
                "repository",
                "Repository health",
                SignalStatus.FAILURE,
                "The repository is archived or disabled.",
            )
        if repository.get("has_pull_requests") is False:
            return _check(
                "repository",
                "Repository health",
                SignalStatus.FAILURE,
                "Pull requests are disabled for this repository.",
            )
        pushed_at = _datetime(repository.get("pushed_at"))
        if pushed_at and (datetime.now(UTC) - pushed_at).days > 180:
            age_days = (datetime.now(UTC) - pushed_at).days
            return _check(
                "repository",
                "Repository health",
                SignalStatus.WARNING,
                f"The default repository activity is {age_days} days old.",
            )
        return _check(
            "repository",
            "Repository health",
            SignalStatus.PASS,
            "The repository is active and accepts pull requests.",
        )

    @staticmethod
    def _ci_check(result: FetchResult[list[JsonObject]]) -> CheckResult:
        if result.error:
            return _unknown("default_branch_ci", "Default branch CI", result.error)
        runs = result.value or []
        if not runs:
            return _check(
                "default_branch_ci",
                "Default branch CI",
                SignalStatus.INFO,
                "No completed GitHub Actions runs were found on the default branch.",
            )

        latest_by_workflow: dict[str, JsonObject] = {}
        for run in runs:
            name = _string(run.get("name")) or "Unnamed workflow"
            latest_by_workflow.setdefault(name, run)
        unhealthy = [
            run
            for run in latest_by_workflow.values()
            if run.get("conclusion") not in {"success", "skipped", "neutral"}
        ]
        if unhealthy:
            return _check(
                "default_branch_ci",
                "Default branch CI",
                SignalStatus.WARNING,
                "At least one latest default-branch workflow is not green.",
                [
                    Evidence(
                        text=f"{run.get('name', 'Workflow')}: {run.get('conclusion', 'unknown')}",
                        url=_url(run.get("html_url")),
                    )
                    for run in unhealthy
                ],
            )
        return _check(
            "default_branch_ci",
            "Default branch CI",
            SignalStatus.PASS,
            f"Latest runs for {len(latest_by_workflow)} workflow(s) are green.",
        )

    @staticmethod
    def _maintainer_response_check(
        issue: JsonObject, result: FetchResult[list[JsonObject]]
    ) -> CheckResult:
        if result.error:
            return _unknown("maintainer_response", "Maintainer response", result.error)
        created_at = _datetime(issue.get("created_at"))
        maintainer_comments = [
            comment
            for comment in result.value or []
            if comment.get("author_association") in MAINTAINER_ASSOCIATIONS
        ]
        if maintainer_comments:
            first = min(
                maintainer_comments,
                key=lambda item: (
                    _datetime(item.get("created_at")) or datetime.max.replace(tzinfo=UTC)
                ),
            )
            response_at = _datetime(first.get("created_at"))
            response = "A maintainer has replied."
            if created_at and response_at:
                hours = max(0, int((response_at - created_at).total_seconds() // 3600))
                response = f"A maintainer first replied after approximately {hours} hour(s)."
            return _check(
                "maintainer_response",
                "Maintainer response",
                SignalStatus.PASS,
                response,
                [Evidence(text="First maintainer reply", url=_url(first.get("html_url")))],
            )
        age_days = (datetime.now(UTC) - created_at).days if created_at else 0
        status = SignalStatus.WARNING if age_days >= 7 else SignalStatus.INFO
        return _check(
            "maintainer_response",
            "Maintainer response",
            status,
            "No maintainer response was found on this issue."
            if age_days < 7
            else f"No maintainer response was found after {age_days} days.",
        )

    @staticmethod
    def _overall_status(checks: Iterable[CheckResult]) -> OverallStatus:
        check_list = list(checks)
        if any(
            check.key in HARD_BLOCKER_KEYS and check.status == SignalStatus.FAILURE
            for check in check_list
        ):
            return OverallStatus.BLOCKED
        if any(
            check.status in {SignalStatus.WARNING, SignalStatus.UNKNOWN, SignalStatus.FAILURE}
            for check in check_list
        ):
            return OverallStatus.CAUTION
        return OverallStatus.READY

    @staticmethod
    def _next_actions(checks: list[CheckResult], status: OverallStatus) -> list[str]:
        by_key = {check.key: check for check in checks}
        actions: list[str] = []
        if by_key["dependencies"].status == SignalStatus.FAILURE:
            actions.append("Wait for the listed dependency issues to close.")
        if by_key["base_branch"].status == SignalStatus.FAILURE:
            actions.append("Ask the maintainer to create or clarify the required base branch.")
        if by_key["assignment"].status == SignalStatus.FAILURE:
            actions.append("Coordinate with the current assignee before writing code.")
        if by_key["claims"].status == SignalStatus.WARNING:
            actions.append("Confirm the comment claim is inactive before starting.")
        if by_key["competing_prs"].status == SignalStatus.WARNING:
            actions.append("Review the linked pull request before proposing duplicate work.")
        if by_key["default_branch_ci"].status == SignalStatus.WARNING:
            actions.append("Separate pre-existing CI failures from failures caused by your change.")
        if by_key["contribution_docs"].status == SignalStatus.PASS:
            actions.append("Read the repository contribution guide before creating a branch.")
        if status == OverallStatus.READY:
            actions.append("Comment with a concise implementation plan before starting work.")
        return actions or ["Review unknown checks manually before starting work."]


def _check(
    key: str,
    title: str,
    status: SignalStatus,
    summary: str,
    evidence: list[Evidence] | None = None,
) -> CheckResult:
    return CheckResult(
        key=key,
        title=title,
        status=status,
        summary=summary,
        evidence=evidence or [],
    )


def _unknown(key: str, title: str, error: Exception | None) -> CheckResult:
    detail = str(error) if error else "No diagnostic was returned."
    return _check(
        key,
        title,
        SignalStatus.UNKNOWN,
        f"Could not verify this signal: {detail}",
    )


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _url(value: Any) -> HttpUrl | None:
    candidate = _string(value)
    if not candidate or not candidate.startswith(("https://", "http://")):
        return None
    return HttpUrl(candidate)


def _datetime(value: Any) -> datetime | None:
    candidate = _string(value)
    if not candidate:
        return None
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None


def _logins(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        login
        for item in value
        if isinstance(item, dict) and (login := _string(item.get("login"))) is not None
    ]


def _nested_object(value: JsonObject, *keys: str) -> JsonObject | None:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return cast(JsonObject, current) if isinstance(current, dict) else None


def _nested_string(value: JsonObject, *keys: str) -> str | None:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _string(current)
