# Contributing

Thank you for improving DSH Company. By participating, you agree to the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

Clone recursively so the pinned DSH submodule is present:

```powershell
git clone --recurse-submodules <repository-url>
cd dsh-company
```

When project manifests and lockfiles are present, keep them synchronized. Use a short-lived,
descriptive conventional branch such as `feat/<topic>`, `fix/<topic>`, or `docs/<topic>`.

## Repository boundaries

- `apps/company-service` contains the Python service.
- `apps/dsh-company-plugin` contains the DSH plugin.
- `vendor/deepseek-harness` is pinned upstream source; do not edit it as part of application changes.

Keep changes focused and do not commit generated dependencies or local application data.

## Tests and pull requests

Run the smallest focused check while developing. Before opening a pull request, run the public,
keyless repository gate:

```powershell
python tools/check.py
```

Also check the patch for whitespace errors:

```powershell
git diff --check
```

Never commit credentials or place them in `.env`, tests, fixtures, logs, screenshots, or
documentation. Pull requests should explain intent, user-visible effects, tests, compatibility
impact, and any remaining risk. Keep unrelated changes out and update public documentation when
behavior changes.
