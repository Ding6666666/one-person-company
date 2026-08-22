import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_python_workspace_contains_only_the_company_service() -> None:
    with (ROOT / "pyproject.toml").open("rb") as workspace_file:
        workspace = tomllib.load(workspace_file)

    assert workspace["project"]["dependencies"] == ["dsh-company-service"]
    assert workspace["tool"]["uv"]["workspace"]["members"] == [
        "apps/company-service"
    ]


def test_node_workspace_contains_only_company_products() -> None:
    workspace_lines = [
        line.strip()
        for line in (ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("-")
    ]
    plugin_package = json.loads(
        (ROOT / "apps/dsh-company-plugin/package.json").read_text(encoding="utf-8")
    )
    sdk_package = json.loads(
        (ROOT / "packages/company-plugin-sdk/package.json").read_text(encoding="utf-8")
    )

    assert workspace_lines == [
        "- apps/dsh-company-plugin",
        "- packages/company-plugin-sdk",
    ]
    assert plugin_package["name"] == "@dsh/company-plugin-build"
    assert sdk_package["name"] == "@dsh/company-plugin-sdk"
    assert sdk_package.get("dependencies", {}) == {}


def test_repository_root_is_the_public_dsh_bundle() -> None:
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "@dsh/company-plugin"
    assert manifest["private"] is False
    assert manifest["license"] == "Apache-2.0"
    assert manifest["repository"]["url"] == (
        "git+https://github.com/Ding6666666/one-person-company.git"
    )
    assert manifest["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"


def test_dsh_submodule_uses_the_pinned_vendor_location() -> None:
    gitmodules = (ROOT / ".gitmodules").read_text(encoding="utf-8")

    assert "path = vendor/deepseek-harness" in gitmodules
    assert "url = https://github.com/Ding6666666/deepseek-harness.git" in gitmodules


def test_ci_fetches_the_history_required_by_contract_provenance() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "fetch-depth: 0" in workflow


def test_public_tree_excludes_private_plans_and_runtime_artifacts() -> None:
    assert not (ROOT / "docs/superpowers/plans").exists()
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in (
        ".env",
        ".env.*",
        "**/.venv/",
        "**/node_modules/",
        "dsh-company-data/",
        "*.log",
    ):
        assert entry in ignored


def test_reuse_document_records_both_source_commits() -> None:
    reuse_document = (ROOT / "docs/development/multi-agent-reuse.md").read_text(
        encoding="utf-8"
    )

    assert "2330adbb89cd72cba29f4ed17b70f37036fecaba" in reuse_document
    assert "2db6ebd58523d14dca278e366ea0eb40499702b9" in reuse_document


def test_public_documentation_explains_the_dsh_plugin_workflow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = (ROOT / "docs/development/plugin-installation.md").read_text(
        encoding="utf-8"
    )
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    combined = "\n".join((readme, installation, contributing, security))

    install_command = (
        "dsh plugin --profile web add "
        "github:Ding6666666/one-person-company"
    )
    assert install_command in readme
    assert install_command in installation
    assert "allowBuilds:" in installation
    assert "@dsh/company-plugin" in installation
    assert "dsh plugin --profile web remove @dsh/company-plugin" in installation
    assert "git clone --recurse-submodules" in contributing
    assert "uv run python tools/check.py" in readme
    for variable in (
        "DSH_COMPANY_PYTHON",
        "DSH_COMPANY_SERVICE_ROOT",
        "DSH_COMPANY_DATA_ROOT",
    ):
        assert variable in readme
        assert variable in installation
    assert "runtime_process_lost" in readme
    assert "approval_control_not_exposed" in readme
    assert "github.com/Ding6666666/one-person-company" in combined
    assert "github.com/your-name" not in combined
    assert "github.com/OWNER" not in combined
