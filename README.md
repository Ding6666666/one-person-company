# DSH Company

DSH Company is an independent open-source project built on DSH.

This repository is currently establishing its engineering foundation. The application will be
organized as a Python service in `apps/company-service` and a DSH plugin in
`apps/dsh-company-plugin`. The upstream DSH source is recorded as a pinned submodule at
`vendor/deepseek-harness`.

Clone recursively to obtain the pinned source:

```powershell
git clone --recurse-submodules <repository-url>
cd dsh-company
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines and [SECURITY.md](SECURITY.md)
for private vulnerability reporting. Licensed under the [Apache License 2.0](LICENSE).
