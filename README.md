# One Person Company for DSH

One Person Company is an open-source [DeepSeek Harness (DSH)](https://github.com/deepseek-ai/deepseek-harness) plugin for running a durable, governed company of AI employees. It adds Company workspaces, versioned employees, Direct/Star/Graph/Battle work strategies, approvals, delegation, history, and declarative business plugins while leaving agent execution, sessions, tools, skills, connectors, and personal memory under DSH authority.

The repository root is the installable DSH bundle (`@dsh/company-plugin`). The TypeScript Host starts the loopback Company Service, the React Client renders authoritative projections, and the Python service owns Company facts in SQLite. Company stores safe lifecycle facts and artifact references; it does not copy model transcripts, tool arguments, prompts, or final responses into its database.

## Requirements

- DSH with the `dsh` CLI available on `PATH`.
- Node.js 22.19 or newer and pnpm 11 or newer.
- Python 3.13 and [uv](https://docs.astral.sh/uv/).
- Windows uses DSH's supported Node carrier. Other supported DSH platforms use the same packaged carrier contract.

## Install as a DSH plugin

Install the source-hosted bundle into the `web` profile:

```console
dsh plugin --profile web add github:Ding6666666/one-person-company
```

Git-hosted DSH plugins build from source through their `prepare` script. pnpm 10 and newer blocks that script until the profile explicitly allows it. On the first attempt, copy the exact package key printed by pnpm into the profile's `pnpm-workspace.yaml` under `allowBuilds`, then run the same command again. This grants trusted install-time code execution outside the agent sandbox. Pin a reviewed commit when reproducibility matters:

```console
dsh plugin --profile web add github:Ding6666666/one-person-company#<commit-sha>
```

See [Plugin installation](docs/development/plugin-installation.md) for the exact allow, update, remove, local checkout, data, and troubleshooting workflow.

## Configuration and data

The bundle works without path overrides. It runs the packaged Company Service with uv and stores its environment and SQLite database beneath the profile-owned Company data directory. These optional environment variables override the package defaults:

| Variable | Purpose |
|---|---|
| `DSH_COMPANY_PYTHON` | Use an explicit Python executable instead of packaged uv launch. |
| `DSH_COMPANY_SERVICE_ROOT` | Use an alternate Company Service directory. |
| `DSH_COMPANY_DATA_ROOT` | Choose the persistent Company data root. |

Creating workspaces and employees is local and does not start DSH or require a provider credential. When work is dispatched, the Host passes only the selected DSH credential to the loopback child process. Do not commit `.env` files, databases, logs, profile data, or credentials.

## Capabilities

- Durable Workspace, Employee, immutable EmployeeRevision, binding, Work, Attempt, graph, approval, delegation, event, and artifact-reference facts.
- Direct, Star, explicit Graph, and Battle strategies on a SQLite-backed orchestration engine.
- Four-layer Company authorization: Workspace, Employee revision, Work Node, and DSH Runtime Profile.
- Approval persisted before dispatch and rechecked against current policy after approval.
- Same-Workspace bounded delegation with immutable graph revisions and artifact-reference-only return.
- Public REST/OpenAPI surface, generated TypeScript SDK, Host/Client plugin, and accessible management UI.
- Declarative Company business-plugin catalog and templates. These extend Company policy facts; they are not dynamically injected DSH tools, skills, or connectors.
- Fixed keyless system evaluation across seven task families and fourteen task/strategy pairs.

## Repository structure

```text
apps/
  company-service/          Python Company API, domain, persistence and orchestration
  dsh-company-plugin/       DSH Host lifecycle and React Client
packages/
  company-plugin-sdk/       Generated public TypeScript SDK
  contracts/                OpenAPI snapshot, provenance and generators
benchmarks/company/         Safe fixed-set tasks and baseline metrics
docs/                       Product, architecture and development documentation
evaluation/                 MASEval adapter and fixed evaluation runner
tests/system/               Keyless cross-component acceptance tests
tools/                      Public verification and git-package tooling
vendor/deepseek-harness/    Pinned DSH Git submodule
```

The main architecture map is in [System architecture](docs/architecture/system.md), and [the documentation index](docs/README.md) routes to product and development references.

## Develop from source

```console
git clone --recurse-submodules https://github.com/Ding6666666/one-person-company.git
cd one-person-company
uv sync --all-packages --all-groups
pnpm --dir vendor/deepseek-harness install --frozen-lockfile
pnpm install --frozen-lockfile
```

Run the complete public keyless gate:

```console
uv run python tools/check.py
```

The gate checks the Python lock, Ruff, Pyright, pinned DSH builds and runtime, Company system scenarios, evaluation, migrations, OpenAPI contracts, Host/Client builds and tests, and SDK builds/tests. It uses a loopback keyless endpoint and does not require or read a real provider key.

See [Contributing](CONTRIBUTING.md) for focused commands and contract ownership.

## Verified DSH limits

- The fixed public DSH SDK does not expose cross-process cold Session resume. A running attempt found after restart is recorded as `blocked/runtime_process_lost`; Company does not fabricate Memory or resume semantics.
- A DSH-produced approval control request cannot truthfully continue an already-running attempt with the public SDK, so it closes as `approval_control_not_exposed`. Operators decide persisted pre-dispatch approvals through Company APIs/UI.
- Runtime Profiles do not expose `external.publish`; approval cannot create an unavailable runtime capability.
- Company business-plugin actions remain policy/catalog facts and do not become DSH tools automatically.

The evidence and exact product consequences are recorded in the [DSH capability matrix](docs/development/dsh-capability-matrix.md) and [strategy selection](docs/development/strategy-selection.md).

## Security and license

Report vulnerabilities through the repository's [private security advisory form](https://github.com/Ding6666666/one-person-company/security/advisories/new). See [SECURITY.md](SECURITY.md) for the policy.

Licensed under the [Apache License 2.0](LICENSE).
