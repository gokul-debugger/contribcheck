"""Conservative parsers for GitHub references and issue metadata."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from contribcheck.exceptions import InvalidIssueURLError
from contribcheck.models import IssueTarget

_SHORTHAND_RE = re.compile(
    r"^(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))"
    r"/(?P<repo>[A-Za-z0-9_.-]+)#(?P<number>[1-9][0-9]*)$"
)

_BASE_BRANCH_PATTERNS = (
    re.compile(r"base\s+branch\s*:\s*(?:\*\*)?`([^`]+)`", re.IGNORECASE),
    re.compile(r"(?:target|targets|targeting)\s+(?:the\s+)?(?:\*\*)?`([^`]+)`", re.IGNORECASE),
)


def parse_issue_reference(value: str) -> IssueTarget:
    """Parse a GitHub issue URL or ``owner/repository#number`` shorthand."""

    candidate = value.strip()
    shorthand = _SHORTHAND_RE.fullmatch(candidate)
    if shorthand:
        return IssueTarget(
            owner=shorthand.group("owner"),
            repository=shorthand.group("repo"),
            number=int(shorthand.group("number")),
        )

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "github.com",
        "www.github.com",
    }:
        raise InvalidIssueURLError("Use a github.com issue URL or owner/repository#number.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 4 or parts[2] != "issues" or not parts[3].isdigit():
        raise InvalidIssueURLError("The URL must point to a GitHub issue, not a repository or PR.")

    return IssueTarget(owner=parts[0], repository=parts[1], number=int(parts[3]))


def extract_base_branch(body: str | None) -> str | None:
    """Extract only an explicitly documented target/base branch."""

    if not body:
        return None
    for pattern in _BASE_BRANCH_PATTERNS:
        if match := pattern.search(body):
            return match.group(1).strip()
    return None


def comment_claims_work(body: str) -> bool:
    """Return whether a comment contains a reasonably explicit work claim."""

    normalized = " ".join(_unquoted_markdown(body).casefold().split())
    patterns = (
        r"\bi(?:'d| would) like to (?:work on|take|pick up)\b",
        r"\bi(?:'m| am) (?:working on|taking|picking up)\b",
        r"\bi can (?:work on|take|pick up)\b",
        r"\bplease assign (?:this|it) to me\b",
        r"\bclaim(?:ing)? (?:this|it)\b",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def _unquoted_markdown(body: str) -> str:
    """Remove quoted and fenced text before interpreting a comment as a claim."""

    visible_lines: list[str] = []
    in_fence = False
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or stripped.startswith(">"):
            continue
        visible_lines.append(line)
    return "\n".join(visible_lines)
