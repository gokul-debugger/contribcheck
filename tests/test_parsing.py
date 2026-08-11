from __future__ import annotations

import pytest

from contribcheck.exceptions import InvalidIssueURLError
from contribcheck.parsing import comment_claims_work, extract_base_branch, parse_issue_reference


@pytest.mark.parametrize(
    ("reference", "owner", "repository", "number"),
    [
        ("https://github.com/sigma67/ytmusicapi/issues/986", "sigma67", "ytmusicapi", 986),
        ("https://www.github.com/org/repo/issues/12?tab=comments", "org", "repo", 12),
        ("gokul-debugger/contribcheck#1", "gokul-debugger", "contribcheck", 1),
    ],
)
def test_parse_issue_reference(reference: str, owner: str, repository: str, number: int) -> None:
    target = parse_issue_reference(reference)

    assert target.owner == owner
    assert target.repository == repository
    assert target.number == number


@pytest.mark.parametrize(
    "reference",
    [
        "https://github.com/owner/repo",
        "https://github.com/owner/repo/pull/1",
        "https://example.com/owner/repo/issues/1",
        "owner/repo#0",
    ],
)
def test_parse_issue_reference_rejects_non_issues(reference: str) -> None:
    with pytest.raises(InvalidIssueURLError):
        parse_issue_reference(reference)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("**Base branch: `ytmusicapi-2`.**", "ytmusicapi-2"),
        ("All work targets the **`release/v2`** branch.", "release/v2"),
        ("Open a normal pull request.", None),
        (None, None),
    ],
)
def test_extract_base_branch(body: str | None, expected: str | None) -> None:
    assert extract_base_branch(body) == expected


@pytest.mark.parametrize(
    "body",
    [
        "I'd like to work on this issue.",
        "I am working on this now.",
        "Please assign this to me.",
        "I can pick up this task.",
    ],
)
def test_comment_claims_work_detects_explicit_claims(body: str) -> None:
    assert comment_claims_work(body)


@pytest.mark.parametrize(
    "body",
    [
        "This also happens to me.",
        "Would anyone like to work on this?",
        "Thanks for fixing this.",
        "> I'd like to work on this issue.\n\nHas this contributor started?",
        "```text\nI am working on this now.\n```\nIs this still current?",
    ],
)
def test_comment_claims_work_avoids_general_discussion(body: str) -> None:
    assert not comment_claims_work(body)
