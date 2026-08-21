# DSH Company

DSH Company is an independent open-source project built on DSH. The repository now contains the
Phase 1 engineering foundation and public DSH capability evidence, the Phase 2 Company Core, and
the Phase 3 Direct Work loop:
Workspace and Employee domain models, immutable Employee revisions, capability grants, stable DSH
bindings, SQLite persistence, loopback APIs, direct execution/history/cancellation, and the
management UI.

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

The service exposes `/health` together with Workspace, Employee, Work, event-history, and
cancellation endpoints. When the
DSH Host starts it, Company data is stored in `company.db` beneath `DSH_COMPANY_DATA_ROOT` and is
recovered after a service restart. Creating a Workspace or Employee is entirely local: it neither
requires provider credentials nor starts DSH. Direct Work starts one Attempt-owned public DSH
Harness; the Host passes the selected DeepSeek credential explicitly to the child service. Company
stores only authoritative lifecycle facts, safe event projections, and a `dsh-session://` artifact
reference—not the raw transcript, tool arguments, or final model text.

The public gate runs the fixed DSH runtime against a local keyless model endpoint before the full
service, contract, and plugin checks. It does not read or forward a Provider credential.

The fixed public DSH SDK does not expose cold Session resume. Employee bindings therefore remain
stable Company facts across restart, but they must not be interpreted as proof that a stopped DSH
runtime can resume its former live Session. See the
[DSH capability matrix](docs/development/dsh-capability-matrix.md) for the verified boundary.
The same limitation is visible in Direct Work: after one Attempt closes its Harness, another Work
bound to the same Session ID returns the SDK's closed error result before a second model request.
Company records `failed/gateway_error`; it does not report completion or construct substitute
Memory/resume behavior. A running Attempt found after service restart is instead recorded as
`blocked/runtime_process_lost`.

See [the documentation index](docs/README.md), [CONTRIBUTING.md](CONTRIBUTING.md) for contribution
guidelines, and [SECURITY.md](SECURITY.md) for private vulnerability reporting. Licensed under the
[Apache License 2.0](LICENSE).
