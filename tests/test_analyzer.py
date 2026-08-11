from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from contribcheck.analyzer import IssueAnalyzer
from contribcheck.exceptions import GitHubAPIError
from contribcheck.models import IssueTarget, JsonObject, OverallStatus, SignalStatus


def _timestamp(*, days_ago: int = 0, hours_ago: int = 0) -> str:
    value = datetime.now(UTC) - timedelta(days=days_ago, hours=hours_ago)
    return value.isoformat().replace("+00:00", "Z")


@dataclass
class FakeGitHubReader:
    repository: JsonObject = field(
        default_factory=lambda: {
            "default_branch": "main",
            "archived": False,
            "disabled": False,
            "has_pull_requests": True,
            "pushed_at": _timestamp(days_ago=1),
        }
    )
    issue: JsonObject = field(
        default_factory=lambda: {
            "title": "Focused contribution",
            "state": "open",
            "body": "## Scope\nImplement the focused behavior.\n\n## Definition of done\n"
            + "The tests pass and the behavior is documented. " * 5,
            "assignees": [],
            "created_at": _timestamp(days_ago=2),
        }
    )
    dependencies: list[JsonObject] = field(default_factory=list)
    comments: list[JsonObject] = field(
        default_factory=lambda: [
            {
                "body": "Thanks, this is ready for a contribution.",
                "author_association": "OWNER",
                "created_at": _timestamp(days_ago=1),
                "html_url": "https://github.com/owner/repo/issues/7#issuecomment-1",
                "user": {"login": "maintainer"},
            }
        ]
    )
    timeline: list[JsonObject] = field(default_factory=list)
    search_results: list[JsonObject] = field(default_factory=list)
    paths: set[str] = field(default_factory=lambda: {"CONTRIBUTING.md", "src/package.py"})
    runs: list[JsonObject] = field(
        default_factory=lambda: [
            {
                "name": "CI",
                "conclusion": "success",
                "html_url": "https://github.com/owner/repo/actions/runs/1",
            }
        ]
    )
    branches: dict[str, bool] = field(default_factory=dict)
    dependency_error: Exception | None = None
    search_error: Exception | None = None

    async def get_repository(self, target: IssueTarget) -> JsonObject:
        return self.repository

    async def get_issue(self, target: IssueTarget) -> JsonObject:
        return self.issue

    async def get_blocking_dependencies(self, target: IssueTarget) -> list[JsonObject]:
        if self.dependency_error:
            raise self.dependency_error
        return self.dependencies

    async def get_comments(self, target: IssueTarget) -> list[JsonObject]:
        return self.comments

    async def get_timeline(self, target: IssueTarget) -> list[JsonObject]:
        return self.timeline

    async def search_open_pull_requests(self, target: IssueTarget) -> list[JsonObject]:
        if self.search_error:
            raise self.search_error
        return self.search_results

    async def get_tree_paths(self, target: IssueTarget, ref: str) -> set[str]:
        return self.paths

    async def get_recent_workflow_runs(
        self, target: IssueTarget, branch: str, *, limit: int = 10
    ) -> list[JsonObject]:
        return self.runs

    async def branch_exists(self, target: IssueTarget, branch: str) -> bool:
        return self.branches.get(branch, False)


async def test_ready_issue_has_explainable_report() -> None:
    report = await IssueAnalyzer(FakeGitHubReader()).inspect("owner/repo#7")

    assert report.status == OverallStatus.READY
    assert report.check("dependencies").status == SignalStatus.PASS
    assert report.check("maintainer_response").status == SignalStatus.PASS
    assert report.next_actions[-1].startswith("Comment with")


async def test_open_dependency_and_missing_required_branch_block_work() -> None:
    client = FakeGitHubReader()
    client.issue["body"] = "**Base branch: `future-v2`.**\n\n## Scope\n" + "Details. " * 40
    client.issue["assignees"] = [{"login": "gokul-debugger"}]
    client.dependencies = [
        {
            "number": 6,
            "title": "Foundation",
            "state": "open",
            "html_url": "https://github.com/owner/repo/issues/6",
        }
    ]

    report = await IssueAnalyzer(client).inspect("owner/repo#7", actor="gokul-debugger")

    assert report.status == OverallStatus.BLOCKED
    assert report.check("dependencies").status == SignalStatus.FAILURE
    assert report.check("base_branch").status == SignalStatus.FAILURE
    assert report.check("assignment").status == SignalStatus.PASS
    assert report.next_actions[:2] == [
        "Wait for the listed dependency issues to close.",
        "Ask the maintainer to create or clarify the required base branch.",
    ]


async def test_claim_and_competing_pr_produce_caution_without_false_block() -> None:
    client = FakeGitHubReader()
    client.comments.append(
        {
            "body": "I'd like to work on this issue.",
            "author_association": "NONE",
            "created_at": _timestamp(hours_ago=2),
            "html_url": "https://github.com/owner/repo/issues/7#issuecomment-2",
            "user": {"login": "another-contributor"},
        }
    )
    client.timeline = [
        {
            "event": "cross-referenced",
            "source": {
                "issue": {
                    "title": "Implement issue 7",
                    "state": "open",
                    "html_url": "https://github.com/owner/repo/pull/8",
                    "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/8"},
                }
            },
        }
    ]
    client.search_results = [
        {
            "title": "Implement issue 7",
            "html_url": "https://github.com/owner/repo/pull/8",
        }
    ]

    report = await IssueAnalyzer(client).inspect("owner/repo#7")

    assert report.status == OverallStatus.CAUTION
    assert len(report.check("competing_prs").evidence) == 1
    assert report.check("claims").evidence[0].text == "another-contributor"


async def test_unverifiable_dependency_is_unknown_not_pass() -> None:
    client = FakeGitHubReader(
        dependency_error=GitHubAPIError(403, "Forbidden", endpoint="dependencies")
    )

    report = await IssueAnalyzer(client).inspect("owner/repo#7")

    assert report.status == OverallStatus.CAUTION
    assert report.check("dependencies").status == SignalStatus.UNKNOWN
    assert "Could not verify" in report.check("dependencies").summary


async def test_assignment_to_someone_else_is_a_hard_blocker() -> None:
    client = FakeGitHubReader()
    client.issue["assignees"] = [{"login": "someone-else"}]

    report = await IssueAnalyzer(client).inspect("owner/repo#7", actor="gokul-debugger")

    assert report.status == OverallStatus.BLOCKED
    assert report.check("assignment").evidence[0].text == "someone-else"


async def test_partial_competing_pr_failure_is_not_reported_as_pass() -> None:
    client = FakeGitHubReader(
        search_error=GitHubAPIError(403, "Forbidden", endpoint="search/issues")
    )
    report = await IssueAnalyzer(client).inspect("owner/repo#7")

    assert report.status == OverallStatus.CAUTION
    assert report.check("competing_prs").status == SignalStatus.UNKNOWN


async def test_repository_without_pull_requests_is_blocked() -> None:
    client = FakeGitHubReader()
    client.repository["has_pull_requests"] = False

    report = await IssueAnalyzer(client).inspect("owner/repo#7")

    assert report.status == OverallStatus.BLOCKED
    assert report.check("repository").status == SignalStatus.FAILURE
