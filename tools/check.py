"""Run the repository's public, keyless verification gates."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

_SAFE_ENVIRONMENT_NAMES = (
    "APPDATA",
    "CI",
    "COMSPEC",
    "HOME",
    "LANG",
    "LC_ALL",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "PATH",
    "PATHEXT",
    "PNPM_HOME",
    "PROCESSOR_ARCHITECTURE",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "TZ",
    "USERPROFILE",
    "WINDIR",
    "XDG_CACHE_HOME",
)


def repo_root() -> Path:
    """Return the repository root independent of the caller's working directory."""
    return Path(__file__).resolve().parent.parent


def _executable(name: str) -> str:
    """Resolve platform-specific launchers such as pnpm.cmd when available."""
    return shutil.which(name) or name


def keyless_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy only fixed, non-secret process variables without inspecting other names."""
    available = os.environ if source is None else source
    environment = {
        name: value
        for name in _SAFE_ENVIRONMENT_NAMES
        if (value := available.get(name)) is not None
    }
    environment["CI"] = "true"
    environment["DSH_RUNTIME_MODE"] = "node"
    return environment


def check_commands() -> list[tuple[str, ...]]:
    """Return the complete public verification plan."""
    uv = _executable("uv")
    pnpm = _executable("pnpm")
    return [
        (uv, "lock", "--check"),
        (
            uv,
            "run",
            "ruff",
            "check",
            "apps/company-service/src",
            "apps/company-service/tests",
            "tests/system",
            "tools",
        ),
        (uv, "run", "pyright"),
        (
            pnpm,
            "--dir",
            "vendor/deepseek-harness",
            "--config.verify-deps-before-run=warn",
            "run",
            "build:lib",
        ),
        (
            pnpm,
            "--dir",
            "vendor/deepseek-harness",
            "--config.verify-deps-before-run=warn",
            "run",
            "build:python-runtime",
            "--node-only",
            "--skip-build",
        ),
        (
            uv,
            "run",
            "pytest",
            "apps/company-service/tests/dsh_gateway",
            "tests/system/tests/test_phase_3_direct_work.py",
            "tests/system/tests/test_phase_4_governance.py",
            "-q",
        ),
        (
            uv,
            "run",
            "pytest",
            "apps/company-service/tests",
            "tests/system/tests",
            "-q",
        ),
        (pnpm, "run", "check"),
    ]


def main() -> int:
    """Run each gate in order and preserve the first failing exit code."""
    root = repo_root()
    commands = check_commands()
    environment = keyless_environment()
    for index, command in enumerate(commands, start=1):
        print(f"[check] ({index}/{len(commands)}) {' '.join(command)}", flush=True)
        result = subprocess.run(
            command,
            cwd=root,
            env=environment,
            shell=False,
            check=False,
        )
        if result.returncode:
            print(f"[check] stopped: exit code {result.returncode}", flush=True)
            return result.returncode
    print("[check] all keyless gates passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
