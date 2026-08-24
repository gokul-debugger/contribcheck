from __future__ import annotations

from pathlib import Path

import pytest
from click import unstyle
from pydantic import HttpUrl
from typer.testing import CliRunner

from contribcheck.cli import app
from contribcheck.models import (
    CheckResult,
    Evidence,
    InspectionReport,
    IssueTarget,
    OverallStatus,
    SignalStatus,
)

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
        reference: str,
        *,
        actor: str | None,
        token: str | None,
        base_url: str | None = None,
    ) -> InspectionReport:
        assert reference == "owner/repo#7"
        assert actor == "gokul-debugger"
        assert token is None
        assert base_url == "https://github.example/api/v3"
        return _report()

    monkeypatch.setattr("contribcheck.cli._inspect", fake_inspect)
    result = runner.invoke(
        app,
        [
            "inspect",
            "owner/repo#7",
            "--actor",
            "gokul-debugger",
            "--json",
            "--base-url",
            "https://github.example/api/v3",
        ],
    )

    assert result.exit_code == 0
    assert '"status": "ready"' in result.stdout


def test_inspect_markdown_output_has_links_and_no_ansi(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_inspect(
        reference: str,
        *,
        actor: str | None,
        token: str | None,
        base_url: str | None = None,
    ) -> InspectionReport:
        return InspectionReport(
            target=IssueTarget(owner="owner", repository="repo", number=7),
            title="Ready | issue",
            status=OverallStatus.READY,
            checks=[
                CheckResult(
                    key="scope",
                    title="Issue scope",
                    status=SignalStatus.PASS,
                    summary="The scope is clear.",
                    evidence=[
                        Evidence(
                            text="Issue discussion",
                            url=HttpUrl("https://github.com/owner/repo/issues/7#issuecomment-1"),
                        ),
                        Evidence(text="Plain evidence"),
                    ],
                )
            ],
            next_actions=["Read the guide."],
        )

    monkeypatch.setattr("contribcheck.cli._inspect", fake_inspect)
    result = runner.invoke(app, ["inspect", "owner/repo#7", "--markdown"])

    assert result.exit_code == 0
    assert "## Verdict: READY" in result.stdout
    assert (
        "[Issue discussion](https://github.com/owner/repo/issues/7#issuecomment-1)" in result.stdout
    )
    assert "Plain evidence" in result.stdout
    assert "\\x1b" not in result.stdout


def test_inspect_rejects_json_and_markdown_together() -> None:
    result = runner.invoke(app, ["inspect", "owner/repo#7", "--json", "--markdown"])

    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


def test_inspect_markdown_output_can_be_written_to_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def fake_inspect(
        reference: str,
        *,
        actor: str | None,
        token: str | None,
        base_url: str | None = None,
    ) -> InspectionReport:
        return _report()

    monkeypatch.setattr("contribcheck.cli._inspect", fake_inspect)
    output_file = tmp_path / "report.md"
    result = runner.invoke(
        app,
        ["inspect", "owner/repo#7", "--markdown", "--output", str(output_file)],
    )

    assert result.exit_code == 0
    assert output_file.read_text(encoding="utf-8").startswith("# Ready issue")
    assert result.stdout == ""


def test_inspect_output_requires_structured_format() -> None:
    result = runner.invoke(app, ["inspect", "owner/repo#7", "--output", "report.txt"])

    assert result.exit_code == 2
    normalized_output = " ".join(unstyle(result.output).split())
    assert "requires --json or --markdown" in normalized_output


def test_fail_on_blocked_returns_exit_code_two(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_inspect(
        reference: str,
        *,
        actor: str | None,
        token: str | None,
        base_url: str | None = None,
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
