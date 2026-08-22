# Contributing

Thank you for improving DSH Company. By participating, you agree to the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

Clone the public repository with its pinned DSH submodule, then install the locked dependencies:

```console
git clone --recurse-submodules https://github.com/Ding6666666/one-person-company.git
cd one-person-company
uv sync --all-packages --all-groups
pnpm --dir vendor/deepseek-harness install --frozen-lockfile
pnpm install --frozen-lockfile
```

For an existing clone, `git submodule update --init --recursive` restores the pinned vendor tree.

Use a short-lived, descriptive conventional branch such as `feat/<topic>`, `fix/<topic>`, or
`docs/<topic>`.

## Repository boundaries

- `apps/company-service` contains the Python foundation service.
- `apps/dsh-company-plugin` contains the DSH plugin shell.
- `packages/company-plugin-sdk` contains the generated public TypeScript SDK.
- `packages/contracts` owns the committed OpenAPI transport snapshot, compatibility fixtures, and
  contract tooling.
- Generated TypeScript lives at
  `apps/dsh-company-plugin/src/contracts/generated/openapi.ts`; do not edit it by hand.
- `vendor/deepseek-harness` is pinned upstream source; do not edit it as part of application changes.
- The repository root is the publishable `@dsh/company-plugin` bundle; keep its exports, Cordis patch,
  package file list, and Git `prepare` path aligned.

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

Open issues and pull requests at
[Ding6666666/one-person-company](https://github.com/Ding6666666/one-person-company).
