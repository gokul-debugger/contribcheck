"""Domain-specific exceptions raised by ContribCheck."""


class ContribCheckError(Exception):
    """Base exception for expected ContribCheck failures."""


class InvalidIssueURLError(ContribCheckError, ValueError):
    """Raised when an issue reference cannot be parsed."""


class GitHubAPIError(ContribCheckError):
    """Raised when GitHub returns an unexpected response."""

    def __init__(self, status_code: int, message: str, *, endpoint: str) -> None:
        self.status_code = status_code
        self.endpoint = endpoint
        super().__init__(f"GitHub API returned {status_code} for {endpoint}: {message}")


class GitHubRateLimitError(GitHubAPIError):
    """Raised when the GitHub API rate limit is exhausted."""
