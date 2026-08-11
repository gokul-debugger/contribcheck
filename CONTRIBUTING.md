# Contributing

Thank you for helping improve ContribCheck.

## Before Starting

1. Search existing issues and pull requests for overlapping work.
2. Comment on the issue with a short implementation plan.
3. Wait for confirmation when the issue is assigned or changes a public contract.

## Development Setup

```bash
git clone https://github.com/gokul-debugger/contribcheck.git
cd contribcheck
uv sync --all-extras --dev
```

Run the complete local check set:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov=contribcheck --cov-report=term-missing
```

## Design Rules

- Base verdicts on deterministic, linkable evidence.
- Report unavailable evidence as `unknown`; do not quietly treat it as a pass.
- Keep GitHub access read-only.
- Add a focused test for every new signal or failure mode.
- Avoid heuristics that cannot explain why they fired.

Pull requests should be narrowly scoped and describe the behavior being changed, its motivation, and the checks that were run.
