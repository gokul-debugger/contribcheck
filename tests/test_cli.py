from __future__ import annotations

import pytest
from typer.testing import CliRunner

from contribcheck.cli import app
from contribcheck.models import InspectionReport, IssueTarget, OverallStatus

runner = CliRunner()


def _report(status: OverallStatus = OverallStatus.READY) -> InspectionReport:
    return InspectionReport(
        target=IssueTarget(owner="owner", repository="repo", number=7),
        title="Ready issue",
        status=status,
        checks=[],
        next_actions=["Read the contribution guide."],
    )


def test_inspect_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_inspect(
        reference: str, *, actor: str | None, token: str | None
    ) -> InspectionReport:
        assert reference == "owner/repo#7"
        assert actor == "gokul-debugger"
        assert token is None
        return _report()

    monkeypatch.setattr("contribcheck.cli._inspect", fake_inspect)
    result = runner.invoke(
        app,
        ["inspect", "owner/repo#7", "--actor", "gokul-debugger", "--json"],
    )

    assert result.exit_code == 0
    assert '"status": "ready"' in result.stdout


def test_fail_on_blocked_returns_exit_code_two(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_inspect(
        reference: str, *, actor: str | None, token: str | None
    ) -> InspectionReport:
        return _report(OverallStatus.BLOCKED)

    monkeypatch.setattr("contribcheck.cli._inspect", fake_inspect)
    result = runner.invoke(
        app,
        ["inspect", "owner/repo#7", "--json", "--fail-on", "blocked"],
    )

    assert result.exit_code == 2


def test_version_command() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"
