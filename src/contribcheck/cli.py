"""Command-line interface for ContribCheck."""

from __future__ import annotations

import asyncio
import os
from enum import StrEnum
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.table import Table

from contribcheck import __version__
from contribcheck.analyzer import IssueAnalyzer
from contribcheck.exceptions import ContribCheckError
from contribcheck.github import GitHubClient
from contribcheck.models import InspectionReport, OverallStatus, SignalStatus

app = typer.Typer(
    name="contribcheck",
    help="Check whether a GitHub issue is genuinely ready for contribution.",
    no_args_is_help=True,
)
console = Console()


class FailOn(StrEnum):
    """CLI exit-code threshold."""

    NEVER = "never"
    BLOCKED = "blocked"
    CAUTION = "caution"


@app.command()
def inspect(
    reference: Annotated[
        str,
        typer.Argument(help="GitHub issue URL or owner/repository#number."),
    ],
    actor: Annotated[
        str | None,
        typer.Option(help="Treat assignments and claims by this GitHub user as your own."),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(envvar="GITHUB_TOKEN", hidden=True),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the complete report as JSON."),
    ] = False,
    fail_on: Annotated[
        FailOn,
        typer.Option(help="Return a non-zero exit code at this readiness threshold."),
    ] = FailOn.NEVER,
) -> None:
    """Inspect one public GitHub issue."""

    try:
        report = asyncio.run(_inspect(reference, actor=actor, token=token))
    except (ContribCheckError, httpx.HTTPError, ValueError) as error:
        console.print(f"[bold red]Inspection failed:[/bold red] {error}", highlight=False)
        raise typer.Exit(code=1) from error

    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    else:
        _render_report(report)

    if fail_on == FailOn.BLOCKED and report.status == OverallStatus.BLOCKED:
        raise typer.Exit(code=2)
    if fail_on == FailOn.CAUTION and report.status != OverallStatus.READY:
        raise typer.Exit(code=2)


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535, help="Port to bind.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Reload when source files change.")] = False,
) -> None:
    """Run the optional FastAPI service."""

    try:
        import uvicorn
    except ImportError as error:
        console.print(
            "[red]Server dependencies are missing.[/red] Install with "
            "[bold]pip install 'contribcheck[server]'[/bold]."
        )
        raise typer.Exit(code=1) from error
    uvicorn.run("contribcheck.api:app", host=host, port=port, reload=reload)


def version_callback(value: bool) -> None:
    """Print the package version and exit."""

    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, is_eager=True),
    ] = None,
) -> None:
    """ContribCheck CLI."""


async def _inspect(reference: str, *, actor: str | None, token: str | None) -> InspectionReport:
    async with GitHubClient(token=token) as client:
        resolved_actor = actor or os.getenv("GITHUB_ACTOR")
        return await IssueAnalyzer(client).inspect(reference, actor=resolved_actor)


def _render_report(report: InspectionReport) -> None:
    colors = {
        OverallStatus.READY: "green",
        OverallStatus.CAUTION: "yellow",
        OverallStatus.BLOCKED: "red",
    }
    console.print()
    console.print(f"[bold]{report.title}[/bold]")
    console.print(report.target.url, style="blue underline")
    console.print(
        f"Verdict: [{colors[report.status]}]{report.status.value.upper()}[/]",
        highlight=False,
    )
    console.print()

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Status", width=9)
    table.add_column("Check", min_width=20)
    table.add_column("Finding")
    status_styles = {
        SignalStatus.PASS: "green",
        SignalStatus.WARNING: "yellow",
        SignalStatus.FAILURE: "red",
        SignalStatus.UNKNOWN: "magenta",
        SignalStatus.INFO: "cyan",
    }
    for check in report.checks:
        table.add_row(
            f"[{status_styles[check.status]}]{check.status.value.upper()}[/]",
            check.title,
            check.summary,
        )
        for evidence in check.evidence:
            suffix = f" ({evidence.url})" if evidence.url else ""
            table.add_row("", "", f"[dim]{evidence.text}{suffix}[/dim]")
    console.print(table)

    console.print("\n[bold]Next actions[/bold]")
    for action in report.next_actions:
        console.print(f"- {action}")


if __name__ == "__main__":
    app()
