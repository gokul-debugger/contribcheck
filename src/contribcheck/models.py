"""Typed domain models for inspection inputs and reports."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, computed_field


class StrictModel(BaseModel):
    """Base model that rejects accidental fields in public contracts."""

    model_config = ConfigDict(extra="forbid")


class SignalStatus(StrEnum):
    """Outcome of one deterministic readiness check."""

    PASS = "pass"
    WARNING = "warning"
    FAILURE = "failure"
    UNKNOWN = "unknown"
    INFO = "info"


class OverallStatus(StrEnum):
    """Overall issue readiness verdict."""

    READY = "ready"
    CAUTION = "caution"
    BLOCKED = "blocked"


class IssueTarget(StrictModel):
    """Canonical coordinates for a GitHub issue."""

    owner: str
    repository: str
    number: int = Field(gt=0)
    host: str = "github.com"

    @property
    def full_name(self) -> str:
        """Return the conventional owner/repository identifier."""

        return f"{self.owner}/{self.repository}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        """Return the canonical browser URL."""

        return f"https://{self.host}/{self.full_name}/issues/{self.number}"


class Evidence(StrictModel):
    """One concrete observation supporting a check result."""

    text: str
    url: HttpUrl | None = None


class CheckResult(StrictModel):
    """A named readiness check and its supporting evidence."""

    key: str
    title: str
    status: SignalStatus
    summary: str
    evidence: list[Evidence] = Field(default_factory=list)


class InspectionReport(StrictModel):
    """Complete, machine-readable issue readiness report."""

    target: IssueTarget
    title: str
    status: OverallStatus
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    checks: list[CheckResult]
    next_actions: list[str]

    def check(self, key: str) -> CheckResult:
        """Return a check by key, raising KeyError when it is absent."""

        for result in self.checks:
            if result.key == key:
                return result
        raise KeyError(key)


class BatchItem(StrictModel):
    """One ordered result from a batch inspection."""

    reference: str
    report: InspectionReport | None = None
    error: str | None = None


class BatchSummary(StrictModel):
    """Stable aggregate counts for a batch inspection."""

    total: int
    succeeded: int
    failed: int
    ready: int
    caution: int
    blocked: int


class BatchReport(StrictModel):
    """Machine-readable batch output with a versioned top-level shape."""

    schema_version: Literal[1] = 1
    results: list[BatchItem]
    summary: BatchSummary


class InspectionRequest(StrictModel):
    """HTTP API request body."""

    url: str
    actor: str | None = None


JsonObject = dict[str, Any]
