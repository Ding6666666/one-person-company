from pathlib import Path

from tools.check import check_commands


def _normalized(command: tuple[str, ...]) -> tuple[str, ...]:
    executable = Path(command[0]).stem.lower()
    return (executable, *command[1:])


def test_public_check_runs_all_keyless_gates_in_order() -> None:
    assert [_normalized(command) for command in check_commands()] == [
        ("uv", "lock", "--check"),
        (
            "uv",
            "run",
            "ruff",
            "check",
            "apps/company-service/src",
            "apps/company-service/tests",
            "tests/system",
            "tools",
        ),
        ("uv", "run", "pyright"),
        (
            "uv",
            "run",
            "pytest",
            "apps/company-service/tests",
            "tests/system/tests",
            "-q",
        ),
        (
            "pnpm",
            "--dir",
            "vendor/deepseek-harness",
            "run",
            "build:lib",
        ),
        ("pnpm", "run", "check"),
    ]
