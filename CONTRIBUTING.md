# Contributing

## Setup

```bash
uv sync --extra dev --extra demo --extra api --extra apispec --extra mcp
uv run playwright install chromium
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

The Chromium install is not optional — the suite drives a real browser against the
bundled demo target, so without it every capture test fails at session start.

## Checks

Every pull request must pass all four. They run in CI and, via pre-commit, on your
machine before the push:

```bash
uv run ruff check .        # lint
uv run mypy qai            # types, --strict
uv run pytest -q           # tests
```

Secrets are scanned separately in CI (gitleaks over the working tree).

## Releasing

Tag a version and push the tag:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

The release workflow re-runs the full gate against the tagged commit, builds the
wheel and sdist, and attaches them to a generated GitHub Release.

Publishing to PyPI is not wired. It needs a one-time pending publisher registered on
pypi.org (project name, owner, repo, workflow file, environment) before the first
upload can work — add the publish job only once that exists.
