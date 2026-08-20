# DSH Company

DSH Company is an independent open-source project built on DSH. This repository currently
contains the Phase 1A engineering foundation: a minimal Python service, a DSH plugin shell, and
the committed API transport contract between them. Company Domain, persistence, DSH runtime
integration, and business UI are not implemented yet.

## Repository setup

Run these commands from the repository root. They initialize the pinned upstream DSH source and
install the locked Python, upstream DSH, and workspace JavaScript dependencies:

```powershell
git submodule update --init --recursive
uv sync --all-packages --all-groups
pnpm --dir vendor/deepseek-harness install --frozen-lockfile
pnpm --dir vendor/deepseek-harness run build:lib
pnpm install --frozen-lockfile
```

## Verify and run

Run the same public, keyless gate used by CI from the repository root after dependency setup:

```powershell
uv run python tools/check.py
```

When the repository's Python 3.13 uv environment is activated or its executable directory is on
`PATH`, as in CI, the equivalent invocation is `python tools/check.py`. On Windows, use the
`uv run` form unless that environment is already active so `python` does not resolve to the
Microsoft Store alias.

Start the foundation service locally with:

```powershell
uv run uvicorn dsh_company.asgi:app --host 127.0.0.1 --port 8000
```

The service currently exposes foundation endpoints such as `/health`; it does not provide
Company Domain or DSH runtime behavior.

See [the documentation index](docs/README.md), [CONTRIBUTING.md](CONTRIBUTING.md) for contribution
guidelines, and [SECURITY.md](SECURITY.md) for private vulnerability reporting. Licensed under the
[Apache License 2.0](LICENSE).
