import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]


def run_node(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", *arguments],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def test_root_package_is_a_git_installable_dsh_bundle() -> None:
    result = run_node("tools/audit-plugin-package.mjs", "--manifest-only")

    assert json.loads(result.stdout) == {
        "name": "@dsh/company-plugin",
        "patch": "./cordis.patch.yml",
        "host": "./apps/dsh-company-plugin/dist/index.mjs",
        "client": "./apps/dsh-company-plugin/dist/client.js",
    }


@pytest.mark.parametrize(
    "forbidden_name",
    [
        ".env",
        "config/.env.local",
        "runtime/service.log",
        "docs/superpowers/plans/private.md",
        ".venv/pyvenv.cfg",
        "node_modules/package/index.js",
        "dsh-company.db",
        "dsh-company.db-shm",
        "dsh-company.db-wal",
        "dsh-company-data/company.db",
    ],
)
def test_package_audit_rejects_private_or_runtime_file_names(
    tmp_path: Path,
    forbidden_name: str,
) -> None:
    file_list = tmp_path / "files.txt"
    file_list.write_text(f"package/README.md\npackage/{forbidden_name}\n", encoding="utf-8")

    result = run_node(
        "tools/audit-plugin-package.mjs",
        "--file-list",
        str(file_list),
        check=False,
    )

    assert result.returncode == 1
    assert forbidden_name in result.stderr.replace("\\", "/")
    assert result.stdout == ""


def test_git_prepare_uses_the_reviewed_build_commands() -> None:
    result = run_node("tools/prepare-git-plugin.mjs", "--describe")

    assert json.loads(result.stdout) == [
        [
            "pnpm",
            "--dir",
            "vendor/deepseek-harness",
            "install",
            "--frozen-lockfile",
        ],
        [
            "pnpm",
            "--dir",
            "vendor/deepseek-harness",
            "--config.verify-deps-before-run=warn",
            "run",
            "build:lib",
        ],
        [
            "pnpm",
            "--config.verify-deps-before-run=warn",
            "--filter",
            "@dsh/company-plugin-build",
            "build",
        ],
        [
            "pnpm",
            "--dir",
            "vendor/deepseek-harness",
            "--config.verify-deps-before-run=warn",
            "run",
            "build:python-runtime",
            "--node-only",
            "--skip-build",
        ],
        [
            "node",
            "tools/runtime-archive.mjs",
            "--create",
            "vendor/deepseek-harness/python/sdk-runtime/src/deepseek_harness_runtime/runtime/node",
            "artifacts/dsh-python-node-runtime.tgz",
        ],
    ]


def test_git_prepare_resolves_pnpm_without_a_windows_command_shim() -> None:
    result = run_node("tools/prepare-git-plugin.mjs", "--resolve-pnpm")
    invocation = json.loads(result.stdout)

    if os.name == "nt":
        assert invocation["executable"].lower().endswith("node.exe")
        assert invocation["arguments"][0].replace("\\", "/").endswith(
            "/node_modules/pnpm/bin/pnpm.mjs"
        )
    else:
        assert invocation == {"executable": "pnpm", "arguments": []}


def test_packed_root_contains_the_plugin_and_company_runtime(tmp_path: Path) -> None:
    pnpm = shutil.which("pnpm")
    assert pnpm is not None
    result = subprocess.run(
        [
            pnpm,
            "--config.ignore-scripts=true",
            "pack",
            "--json",
            "--pack-destination",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    pack_json = tmp_path / "pack.json"
    pack_json.write_text(result.stdout, encoding="utf-8")
    parsed = json.loads(result.stdout)
    rows = parsed if isinstance(parsed, list) else [parsed]
    paths = {
        file["path"].replace("\\", "/")
        for row in rows
        for file in row["files"]
    }

    assert {
        "apps/dsh-company-plugin/dist/index.mjs",
        "apps/dsh-company-plugin/dist/client.js",
        "apps/dsh-company-plugin/lib/types/index.d.ts",
        "apps/company-service/src/dsh_company/asgi.py",
        "vendor/deepseek-harness/python/sdk/pyproject.toml",
        "vendor/deepseek-harness/python/sdk-runtime/pyproject.toml",
        "artifacts/dsh-python-node-runtime.tgz",
        "cordis.patch.yml",
        "pyproject.toml",
        "uv.lock",
    } <= paths

    run_node("tools/audit-plugin-package.mjs", "--pack-json", str(pack_json))


def test_packed_root_installs_as_an_isolated_dsh_bundle(tmp_path: Path) -> None:
    pnpm = shutil.which("pnpm")
    assert pnpm is not None
    package_directory = tmp_path / "package"
    package_directory.mkdir()
    packed = subprocess.run(
        [
            pnpm,
            "--config.ignore-scripts=true",
            "pack",
            "--json",
            "--pack-destination",
            str(package_directory),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    packed_rows = json.loads(packed.stdout)
    packed_row = packed_rows[0] if isinstance(packed_rows, list) else packed_rows
    tarball = package_directory / Path(packed_row["filename"]).name

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "package.json").write_text(
        '{"name":"company-plugin-consumer","private":true}\n',
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PNPM_STORE_DIR": str(tmp_path / "pnpm-store"),
        "CI": "true",
    }
    subprocess.run(
        [
            pnpm,
            "add",
            str(tarball),
            "--config.auto-install-peers=false",
            "--config.ignore-scripts=false",
        ],
        cwd=consumer,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    installed = consumer / "node_modules" / "@dsh" / "company-plugin"
    manifest = json.loads((installed / "package.json").read_text(encoding="utf-8"))
    assert manifest["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
    assert (installed / "apps/dsh-company-plugin/dist/index.mjs").is_file()
    assert (installed / "apps/dsh-company-plugin/dist/client.js").is_file()
    assert (installed / "apps/dsh-company-plugin/lib/types/index.d.ts").is_file()
    assert (installed / "artifacts/dsh-python-node-runtime.tgz").is_file()
    assert "name: '@dsh/company-plugin'" in (
        installed / "cordis.patch.yml"
    ).read_text(encoding="utf-8")


def test_runtime_archive_preserves_the_node_dependency_closure(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    nested_module = runtime_root / "node" / "node_modules" / "@fixture" / "runtime"
    nested_module.mkdir(parents=True)
    (nested_module / "index.js").write_text("export const ready = true\n", encoding="utf-8")
    (runtime_root / "node" / "package.json").write_text(
        '{"name":"runtime-fixture"}\n',
        encoding="utf-8",
    )
    cache = runtime_root / "node" / "__pycache__"
    cache.mkdir()
    (cache / "hatch_build.cpython-313.pyc").write_bytes(b"local bytecode")
    archive = tmp_path / "runtime.tgz"

    run_node(
        "tools/runtime-archive.mjs",
        "--create",
        str(runtime_root / "node"),
        str(archive),
    )
    shutil.rmtree(runtime_root / "node")
    run_node(
        "tools/runtime-archive.mjs",
        "--extract",
        str(archive),
        str(runtime_root),
    )

    assert (nested_module / "index.js").read_text(encoding="utf-8") == (
        "export const ready = true\n"
    )
    assert not cache.exists()
