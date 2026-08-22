# DSH Company Open-Source Plugin Publication Design

## Goal

Publish the complete `dsh-company` repository to
`https://github.com/Ding6666666/one-person-company.git` as an open-source DSH
plugin while preserving the existing monorepo, its reviewed Git history, and
the pinned DeepSeek Harness submodule.

The installed repository root must itself be a DSH bundle so this command is
the primary supported installation path:

```console
dsh plugin --profile web add github:Ding6666666/one-person-company
```

## Publication boundaries

- Preserve the current reviewed Git history. Do not rewrite earlier commits.
- Push only the current reviewed ancestry as the target repository's `main`
  branch. Do not publish unrelated local branches.
- Keep `vendor/deepseek-harness` as a Git submodule pointing at its existing
  public repository and pinned revision.
- Back up `docs/superpowers/plans/` to
  `E:\Project\dsh\dsh-company-private-plans\` and remove it from the current
  public tree. Earlier commits will still expose historical contents by design.
- Do not publish `.env` files, credentials, databases, runtime data, logs,
  virtual environments, dependency directories, or generated local caches.
- Do not read, print, copy, or use a real DeepSeek API key during publication.

## Repository structure

The repository remains a source monorepo:

- `apps/company-service/`: Python Company API, domain, persistence, policy,
  orchestration, and migrations.
- `apps/dsh-company-plugin/`: DSH Host and web Client implementation.
- `packages/company-plugin-sdk/`: typed consumer SDK.
- `packages/contracts/`: captured OpenAPI contract and generated TypeScript
  types.
- `evaluation/` and `benchmarks/`: deterministic system evaluation and safe
  baselines.
- `tests/system/`: keyless end-to-end coverage.
- `vendor/deepseek-harness/`: pinned upstream DSH submodule.
- `docs/`: public architecture, development, plugin installation, and verified
  capability documentation.

The root README will lead with the product, DSH plugin installation, runtime
requirements, repository map, configuration, development workflow, verified
checks, and honest fixed-SDK limitations.

## Root DSH bundle

The root package becomes the installable bundle, while
`apps/dsh-company-plugin` remains the internal build workspace.

The root package will:

- use a public package identity such as `@dsh/one-person-company`;
- declare `dsh.bundle.patch` and the existing DSH web client injections;
- export the built Host entry, Client entry, types, patch, and package metadata;
- include repository, license, issue, and homepage metadata;
- use a `prepare` workflow appropriate for DSH git-hosted plugins;
- contain only the runtime/source files required by the bundle plus the public
  repository documentation when packed.

The root Cordis patch will load the root package name. The internal workspace
package stays private and is not presented as the user-installed package.

## Git installation and service runtime

DSH documents that git-hosted plugins build during installation and that pnpm
may require the package to be added to the profile's build allowlist. The README
will state this explicitly rather than treating the warning as an installation
failure.

The prepare workflow will build the Host and Client and stage the pinned DSH
Python runtime needed by the service. The package must not rely on generated
files that exist only in the developer's working tree.

The plugin will derive its package root from its own module location. Unless
the operator supplies explicit overrides, it will:

- run the Python service through `uv run --frozen --no-dev` against the packaged
  workspace;
- place the uv environment, Company database, and DSH sessions beneath the
  configured Company data root rather than inside `node_modules`;
- use the packaged `apps/company-service` source and pinned Harness runtime;
- retain explicit environment/config overrides for development and advanced
  installations.

Required local tools and supported versions (Node.js, pnpm, Python, and uv) will
be documented before the installation command.

## Open-source documentation and metadata

The existing Apache-2.0 license, contribution guide, code of conduct, and
security policy remain authoritative. They will be checked for stale private
references and aligned with the public repository URL.

Public documentation will include:

- a concise architecture and repository map;
- installation, update, removal, configuration, and troubleshooting steps using
  DSH's `plugin --profile` terminology;
- submodule-aware source development instructions;
- the single public verification command and its keyless behavior;
- data locations and deletion/export expectations;
- the fixed SDK limitations already established by the system baseline;
- the distinction between declarative Company business plugins and DSH runtime
  tools/skills/connectors.

No unsupported continuity, dynamic DSH tool exposure, or external publication
capability will be claimed.

## Verification

Each check is tied to a concrete failure:

1. A clean pack/install test must prove the root package is recognized as a DSH
   bundle and that no untracked developer artifact is required.
2. A package-content inspection must fail if secrets, databases, logs, private
   plans, dependency directories, or caches enter the current distributable.
3. Focused Host lifecycle tests must prove package-relative defaults and the uv
   launch command without reading credentials.
4. The existing full keyless gate must catch Python, TypeScript, contracts,
   migrations, Host/Client bundle, SDK, and fixed-set regressions.
5. A clean checkout/install smoke test must exercise the actual git-hosted
   package shape and release all child processes and temporary files.
6. Git checks must confirm the expected commit ancestry, clean working trees,
   unchanged submodule revisions, intended remote, and only the target `main`
   ref before publication.

If any check fails, publication stops and the concrete failure is corrected;
passing unrelated checks will not be used to waive it.

## GitHub publication

After all checks pass:

- configure the target repository as the publication remote;
- verify authenticated ownership and repository visibility;
- push the current reviewed commit to `main` without force;
- push only intentional release tags, if any exist;
- verify the remote branch, submodule link, README rendering, and clone command;
- report the exact published commit and any documented installation limitation.
