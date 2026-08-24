from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from click import unstyle
from pydantic import HttpUrl
from typer.testing import CliRunner

from contribcheck.cli import _batch, _read_batch_references, app
from contribcheck.models import (
    BatchItem,
    BatchReport,
    BatchSummary,
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


def test_batch_json_preserves_input_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    input_file = tmp_path / "candidates.txt"
    input_file.write_text("# comment\nowner/first#1\n\nowner/second#2\n", encoding="utf-8")
    batch_report = BatchReport(
        results=[
            BatchItem(reference="owner/first#1", report=_report()),
            BatchItem(reference="owner/second#2", error="Not found"),
        ],
        summary=BatchSummary(total=2, succeeded=1, failed=1, ready=1, caution=0, blocked=0),
    )

    async def fake_batch(*args: object, **kwargs: object) -> BatchReport:
        return batch_report

    monkeypatch.setattr("contribcheck.cli._batch", fake_batch)
    result = runner.invoke(app, ["batch", str(input_file), "--json"])

    assert result.exit_code == 1
    assert result.stdout.index("owner/first#1") < result.stdout.index("owner/second#2")
    assert '"failed": 1' in result.stdout


def test_batch_bounds_concurrency_and_keeps_partial_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    maximum = 0

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    class FakeAnalyzer:
        def __init__(self, client: FakeClient) -> None:
            del client

        async def inspect(self, reference: str, *, actor: str | None) -> InspectionReport:
            nonlocal active, maximum
            del actor
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0)
            active -= 1
            if reference.endswith("bad#3"):
                raise ValueError("invalid issue")
            return _report()

    monkeypatch.setattr("contribcheck.cli.GitHubClient", FakeClient)
    monkeypatch.setattr("contribcheck.cli.IssueAnalyzer", FakeAnalyzer)
    report = asyncio.run(
        _batch(
            ["owner/first#1", "owner/bad#3", "owner/last#2"],
            actor=None,
            token=None,
            base_url=None,
            concurrency=1,
        )
    )

    assert maximum == 1
    assert [item.reference for item in report.results] == [
        "owner/first#1",
        "owner/bad#3",
        "owner/last#2",
    ]
    assert report.summary.failed == 1
    assert report.results[1].error == "invalid issue"


def test_batch_input_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    input_file = tmp_path / "candidates.txt"
    input_file.write_text("\n# heading\nowner/repo#1\n  # note\nowner/repo#2\n", encoding="utf-8")

    assert _read_batch_references(input_file) == ["owner/repo#1", "owner/repo#2"]


def test_batch_fail_on_caution_returns_exit_code_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    input_file = tmp_path / "candidates.txt"
    input_file.write_text("owner/repo#1\n", encoding="utf-8")
    report = BatchReport(
        results=[BatchItem(reference="owner/repo#1", report=_report(OverallStatus.CAUTION))],
        summary=BatchSummary(total=1, succeeded=1, failed=0, ready=0, caution=1, blocked=0),
    )

    async def fake_batch(*args: object, **kwargs: object) -> BatchReport:
        return report

    monkeypatch.setattr("contribcheck.cli._batch", fake_batch)
    result = runner.invoke(app, ["batch", str(input_file), "--json", "--fail-on", "caution"])

    assert result.exit_code == 2


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
