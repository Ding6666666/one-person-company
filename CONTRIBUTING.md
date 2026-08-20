# Contributing

Thank you for improving DSH Company. By participating, you agree to the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

From the repository root, initialize the pinned DSH submodule and install the locked dependencies:

```powershell
git submodule update --init --recursive
uv sync --all-packages --all-groups
pnpm --dir vendor/deepseek-harness install --frozen-lockfile
pnpm --dir vendor/deepseek-harness run build:lib
pnpm install --frozen-lockfile
```

Use a short-lived, descriptive conventional branch such as `feat/<topic>`, `fix/<topic>`, or
`docs/<topic>`.

## Repository boundaries

- `apps/company-service` contains the Python foundation service.
- `apps/dsh-company-plugin` contains the DSH plugin shell.
- `packages/contracts` owns the committed OpenAPI transport snapshot, compatibility fixtures, and
  contract tooling.
- Generated TypeScript lives at
  `apps/dsh-company-plugin/src/contracts/generated/openapi.ts`; do not edit it by hand.
- `vendor/deepseek-harness` is pinned upstream source; do not edit it as part of application changes.

Keep changes focused and do not commit generated dependencies or local application data. Follow
the [contract ownership rules](docs/development/contracts.md) when changing the service API.

## Tests and pull requests

Run the smallest focused check while developing. Before opening a pull request, run the public,
keyless repository gate from the repository root after dependency setup:

```powershell
uv run python tools/check.py
```

When the repository's Python 3.13 uv environment is activated or its executable directory is on
`PATH`, as in CI, `python tools/check.py` is equivalent. On Windows, use the `uv run` form unless
that environment is already active so `python` does not resolve to the Microsoft Store alias.

CI runs this same gate. It checks the Python lockfile, linting, types and tests, then builds the
pinned DSH library and checks the workspace contract and plugin packages. No model or provider key
is required.

To exercise the currently implemented foundation service locally, run:

```powershell
uv run uvicorn dsh_company.asgi:app --host 127.0.0.1 --port 8000
```

Never commit credentials or place them in `.env`, tests, fixtures, logs, screenshots, or
documentation. Pull requests should explain intent, user-visible effects, tests, compatibility
impact, and any remaining risk. Keep unrelated changes out and update public documentation when
behavior changes.
