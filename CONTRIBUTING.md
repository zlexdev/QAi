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

Every check above also runs on each pull request, so a fork's failing test or type
error blocks the merge.

Secrets are scanned separately in CI (gitleaks over the working tree).

### Running the suite in halves

CI splits it so a typo comes back in minutes instead of half an hour:

```bash
uv run pytest -q -m "not browser"   # ~2s, needs no Chromium
uv run pytest -q -m browser         # ~30 min, drives a real browser
```

You never write the `browser` marker yourself. It is applied automatically to any test
whose module imports the browser stack or uses the `demo_server` fixture, so a new
browser test lands in the right job without anyone remembering to label it.

## Releasing

Tag a version and push the tag:

Bump `version` in `pyproject.toml`, then tag it:

```bash
git tag v0.2.1 && git push origin v0.2.1
```

`publish.yml` re-runs the full gate against the tagged commit, builds the wheel and
sdist, publishes to PyPI, and only then creates the GitHub Release — a release
announcing a version PyPI rejected would advertise an install command that fails.

PyPI auth is OIDC trusted publishing: no token is stored anywhere. It is bound to the
workflow **filename**, so renaming `publish.yml` breaks every publish until the
publisher is updated on pypi.org to match.

A published version is permanent — PyPI does not accept a re-upload of the same
version number. Bump rather than retry.
