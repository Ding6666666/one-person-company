# DSH plugin installation

This repository publishes one DSH bundle from its root package: `@dsh/company-plugin`. DSH installs the bundle into a profile, reads its `dsh.bundle.patch`, and composes the Company Host and Client with that profile.

## Prerequisites

- `dsh`, Node.js 22.19+, pnpm 11+, Python 3.13, and uv are available on `PATH`.
- The target profile can install dependencies from GitHub.
- The operator trusts this repository's install-time `prepare` script.

## Install from GitHub

```console
dsh plugin --profile web add github:Ding6666666/one-person-company
```

The first command may fail because pnpm blocks build scripts from Git dependencies. DSH prints the exact profile directory and pnpm prints the exact package key. Edit that profile's `pnpm-workspace.yaml` and add the printed key; for this bundle it is expected to resolve as:

```yaml
allowBuilds:
  '@dsh/company-plugin': true
```

Then repeat the install command. `allowBuilds` permits the package's `prepare` code to run on the operator's machine outside the agent sandbox. Review the source and prefer a fixed revision for repeatable installation:

```console
dsh plugin --profile web add github:Ding6666666/one-person-company#<commit-sha>
```

If pnpm prints a different exact key, use its printed key rather than guessing.

## Update, inspect, and remove

```console
dsh plugin --profile web why @dsh/company-plugin
dsh plugin --profile web update @dsh/company-plugin
dsh plugin --profile web remove @dsh/company-plugin
```

DSH reconciles the profile's bundle layers after every successful plugin command. Removing the package removes its configuration layer but does not delete Company data.

## Install a local checkout

Clone with the pinned DSH submodule, install the locked dependencies, and build the git package once:

```console
git clone --recurse-submodules https://github.com/Ding6666666/one-person-company.git
cd one-person-company
uv sync --all-packages --all-groups
pnpm --config.ignore-scripts=true install --frozen-lockfile
node tools/prepare-git-plugin.mjs
dsh plugin --profile web add .
```

DSH anchors the relative path to the invoking directory. A built local checkout or a produced tarball does not need a Git dependency build allowance.

## Configuration

No path setting is required for the Git package. The Host resolves the service, uv project, and DSH Node carrier relative to the installed bundle. Optional overrides are:

| Variable | Meaning |
|---|---|
| `DSH_COMPANY_PYTHON` | Explicit Python executable; bypasses the default `uv run --frozen --no-dev` prefix. |
| `DSH_COMPANY_SERVICE_ROOT` | Alternate directory containing the `dsh_company` service project. |
| `DSH_COMPANY_DATA_ROOT` | Persistent SQLite, session workspace, and uv-environment root. |

The profile selects the provider credential through normal DSH configuration. Company does not enumerate ambient credential variables; the Host passes only the selected credential to the loopback service child.

## Data and uninstall behavior

Company data is persistent and intentionally survives plugin update/removal. Back up or remove the explicit `DSH_COMPANY_DATA_ROOT` only when you intend to manage that data. Never publish its database, WAL/SHM files, session workspaces, `.env` files, or logs.

## Troubleshooting

### The first Git install reports a blocked build

Use the profile path and exact package key printed by DSH/pnpm, add it under `allowBuilds`, and repeat the same `add` command. Do not add unrelated packages.

### The Host cannot start Python

Confirm `uv --version` and Python 3.13 are available. If using `DSH_COMPANY_PYTHON`, confirm it points to a Python environment containing the locked Company service dependencies. Remove the override to return to package-relative uv startup.

### The Node carrier is unavailable

Reinstall from a reviewed commit so the package `prepare` step rebuilds `artifacts/dsh-python-node-runtime.tgz`. The Host extracts that archive on first use and verifies DSH's real `packaged-bin.js` carrier entry before spawning Python.

### Work cannot resume after a process restart

This is a published DSH boundary, not a missing installation step. The current public SDK does not expose cold Session resume. Company records `runtime_process_lost` or a truthful gateway failure and does not invent substitute continuity.

### Company business-plugin action is not a DSH tool

Expected. The Company catalog extends templates, policy, approval, and graph facts. It does not dynamically register DSH tools, skills, or connectors. A real DSH runtime capability must already be exposed by its Runtime Profile.

## Verify a source checkout

```console
uv run python tools/check.py
```

This is the complete keyless public gate. It does not use a real provider key.
