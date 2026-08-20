from pathlib import Path

from tools.check import check_commands, keyless_environment


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
            "pnpm",
            "--dir",
            "vendor/deepseek-harness",
            "--config.verify-deps-before-run=warn",
            "run",
            "build:lib",
        ),
        (
            "pnpm",
            "--dir",
            "vendor/deepseek-harness",
            "--config.verify-deps-before-run=warn",
            "run",
            "build:python-runtime",
            "--node-only",
            "--skip-build",
        ),
        (
            "uv",
            "run",
            "pytest",
            "apps/company-service/tests",
            "tests/system/tests",
            "-q",
        ),
        (
            "uv",
            "run",
            "pytest",
            "apps/company-service/tests/dsh_gateway",
            "-q",
        ),
        ("pnpm", "run", "check"),
    ]


def test_keyless_environment_fixes_node_mode_and_excludes_unlisted_values() -> None:
    environment = keyless_environment(
        {"PATH": "fixed-path", "UNLISTED_ENVIRONMENT": "sentinel"}
    )

    assert environment == {
        "PATH": "fixed-path",
        "CI": "true",
        "DSH_RUNTIME_MODE": "node",
    }
