# DSH Company Phase 0 Repository Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一个可在 Windows 与 Ubuntu 上重复安装、构建、测试和发布检查的独立 `dsh-company` 仓库，并交付可运行的 Company Service 健康端点、可构建的 DSH Host/Client 插件空壳和 Python/TypeScript OpenAPI 契约链路。

**Architecture:** Phase 0 只建设工程地基，不创建 Workspace、Employee、Work、权限、编排、数据库表或业务页面。Python workspace 拥有最小 FastAPI 服务；TypeScript workspace 拥有可被 DSH 构建系统识别的双入口插件；OpenAPI 是两端传输契约。DSH 源码作为独立、固定提交的 vendor submodule 存在，`multi-agent` 只作为迁移来源，不成为运行时依赖。

**Tech Stack:** Python 3.13、uv、FastAPI 0.141.1、Pydantic 2.12.5、Pytest 9.1.1、Ruff 0.15.4、Pyright 1.1.411；Node.js 22.19+、pnpm 11.7.0、TypeScript 5.9、tsdown 0.21、Vitest 4.1、OpenAPI TypeScript 7.13；GitHub Actions；Apache-2.0。

---

## 实施边界

本计划是完整架构的第一个独立实施单元。后续按依赖顺序另写四份计划：DSH 公共能力 Spike、Company Foundation 与 Direct 闭环、权限/审批/委派、Work Graph/Battle/评测。后续计划必须使用本阶段真实生成的包、命令和 DSH 验证结果，不能提前假设 SDK 接口。

迁移来源固定为：

- `multi-agent@2330adbb89cd72cba29f4ed17b70f37036fecaba`
- `deepseek-harness@2db6ebd58523d14dca278e366ea0eb40499702b9`

本阶段明确不迁移：CrewAI、旧 Domain/Application、Runtime DSH 适配器、Persistence、Memory、Git collaboration、Host 子进程生命周期和旧产品 UI。契约来源记录只保存 API 提交，不生成不会影响行为的校验哈希。

## 目标文件结构

```text
dsh-company/
├── .github/workflows/ci.yml
├── apps/
│   ├── company-service/
│   │   ├── pyproject.toml
│   │   ├── src/dsh_company/
│   │   │   ├── api/openapi.py
│   │   │   ├── foundation/app.py
│   │   │   ├── foundation/config.py
│   │   │   └── asgi.py
│   │   └── tests/foundation/
│   └── dsh-company-plugin/
│       ├── src/client/index.ts
│       ├── src/contracts/generated/openapi.ts
│       ├── src/index.ts
│       ├── tests/bundle-manifest.spec.ts
│       └── build/type configuration
├── packages/contracts/
│   ├── fixtures/
│   ├── openapi/
│   ├── scripts/
│   └── tests/
├── tests/system/tests/
├── tools/check.py
├── package.json
├── pnpm-workspace.yaml
└── pyproject.toml
```

### Task 1: 建立开源仓库元数据并固定 DSH 来源

**Files:**

- Create: `.editorconfig`
- Create: `.gitattributes`
- Create: `.gitignore`
- Create: `.gitmodules`
- Create: `LICENSE`
- Create: `CODE_OF_CONDUCT.md`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `.github/pull_request_template.md`
- Create: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Create: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Create: `.github/ISSUE_TEMPLATE/config.yml`
- Create: `.github/dependabot.yml`
- Modify: `README.md`

- [ ] **Step 1: 迁移与产品语义无关的仓库规范**

从固定来源提交读取 `.editorconfig`、`.gitattributes`、Apache-2.0 `LICENSE`、行为准则和 GitHub 模板，用 `apply_patch` 在新仓库创建文件。将所有标题、包名和路径改为 `DSH Company`、`apps/company-service` 和 `apps/dsh-company-plugin`，不得保留 `dsh_multi_agent`、`@dsh/multi-agent-plugin`、M1–M7、Git delivery 或 worktree 语义。

`.gitignore` 至少包含以下实际产物：

```gitignore
.worktrees/
.superpowers/
.env
.env.*
!.env.example
**/__pycache__/
**/*.py[cod]
**/.pytest_cache/
**/.ruff_cache/
**/.venv/
**/node_modules/
apps/dsh-company-plugin/dist/
apps/dsh-company-plugin/lib/
.coverage
coverage/
htmlcov/
.DS_Store
Thumbs.db
.idea/
.vscode/
dsh-company.db
dsh-company.db-shm
dsh-company.db-wal
dsh-company-data/
```

- [ ] **Step 2: 添加并固定 DSH submodule**

Run:

```powershell
git submodule add https://github.com/Ding6666666/deepseek-harness.git vendor/deepseek-harness
git -C vendor/deepseek-harness checkout 2db6ebd58523d14dca278e366ea0eb40499702b9
git add .gitmodules vendor/deepseek-harness
git submodule status vendor/deepseek-harness
```

Expected: 输出以一个空格和 `2db6ebd58523d14dca278e366ea0eb40499702b9 vendor/deepseek-harness` 开头；不能出现 `+` 或 `-` 前缀。

- [ ] **Step 3: 验证迁移文本没有夹带旧产品语义**

Run:

```powershell
rg -n "dsh_multi_agent|@dsh/multi-agent-plugin|DSH Multi-Agent|worktree|Delivery|M[1-7]" .editorconfig .gitattributes .gitignore CONTRIBUTING.md SECURITY.md .github README.md
```

Expected: 无匹配。若有匹配，改写对应句子；不要增加兼容说明。

- [ ] **Step 4: Commit**

```powershell
git add .editorconfig .gitattributes .gitignore .gitmodules LICENSE CODE_OF_CONDUCT.md CONTRIBUTING.md SECURITY.md .github README.md vendor/deepseek-harness
git commit -m "chore: establish open source repository foundation"
```

### Task 2: 用 TDD 建立最小 Python Company Service

**Files:**

- Create: `pyproject.toml`
- Create: `apps/company-service/pyproject.toml`
- Create: `apps/company-service/README.md`
- Create: `apps/company-service/src/dsh_company/__init__.py`
- Create: `apps/company-service/src/dsh_company/asgi.py`
- Create: `apps/company-service/src/dsh_company/api/__init__.py`
- Create: `apps/company-service/src/dsh_company/api/openapi.py`
- Create: `apps/company-service/src/dsh_company/foundation/__init__.py`
- Create: `apps/company-service/src/dsh_company/foundation/config.py`
- Create: `apps/company-service/src/dsh_company/foundation/app.py`
- Create: `apps/company-service/tests/foundation/test_config.py`
- Create: `apps/company-service/tests/foundation/test_app.py`
- Generate: `uv.lock`

- [ ] **Step 1: 创建 Python workspace 清单**

Create root `pyproject.toml`:

```toml
[project]
name = "dsh-company-workspace"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = ["dsh-company-service"]

[tool.uv]
package = false

[tool.uv.workspace]
members = ["apps/company-service"]

[tool.uv.sources]
dsh-company-service = { workspace = true }

[dependency-groups]
dev = [
  "httpx==0.28.1",
  "pyright==1.1.411",
  "pytest==9.1.1",
  "ruff==0.15.4",
]

[tool.pytest.ini_options]
testpaths = ["apps/company-service/tests", "tests/system/tests"]
addopts = ["-ra"]
pythonpath = ["."]

[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pyright]
include = ["apps/company-service/src", "apps/company-service/tests", "tests/system", "tools"]
pythonVersion = "3.13"
typeCheckingMode = "basic"
reportMissingTypeStubs = "none"
```

Create `apps/company-service/pyproject.toml`:

```toml
[project]
name = "dsh-company-service"
version = "0.1.0"
description = "DSH Company local control service"
readme = "README.md"
requires-python = ">=3.13,<3.14"
dependencies = [
  "fastapi==0.141.1",
  "pydantic==2.12.5",
  "pydantic-settings==2.14.2",
  "structlog==25.5.0",
  "uvicorn==0.52.3",
]

[build-system]
requires = ["hatchling>=1.28,<2"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dsh_company"]
```

Create the package `__init__.py` files and a short service README, then run:

```powershell
uv lock
uv sync --all-packages --all-groups
```

Expected: both commands exit 0 and `uv.lock` records `dsh-company-service`; it must not contain `crewai`, `pycasbin`, `sqlalchemy` or `deepseek-harness-sdk` in Phase 0.

- [ ] **Step 2: 写出会失败的配置和健康检查测试**

Create `apps/company-service/tests/foundation/test_config.py`:

```python
from dsh_company.foundation.config import Settings


def test_settings_use_company_specific_environment_names(monkeypatch) -> None:
    monkeypatch.setenv("DSH_COMPANY_HOST", "0.0.0.0")
    monkeypatch.setenv("DSH_COMPANY_PORT", "8123")
    monkeypatch.setenv("DSH_COMPANY_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.host == "0.0.0.0"
    assert settings.port == 8123
    assert settings.log_level == "DEBUG"


def test_settings_have_local_keyless_defaults() -> None:
    settings = Settings()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.log_level == "INFO"
```

Create `apps/company-service/tests/foundation/test_app.py`:

```python
from fastapi.testclient import TestClient

from dsh_company.foundation.app import create_app


def test_health_reports_the_company_service_contract() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "dsh-company"}


def test_openapi_uses_the_company_product_identity() -> None:
    schema = create_app().openapi()

    assert schema["info"]["title"] == "DSH Company Service"
    assert schema["info"]["version"] == "0.1.0"
    assert "/health" in schema["paths"]
```

- [ ] **Step 3: 运行测试并确认红灯原因正确**

Run:

```powershell
uv run pytest apps/company-service/tests/foundation -q
```

Expected: collection fails because `dsh_company.foundation.config` and `dsh_company.foundation.app` do not exist. If failure来自环境或包安装，先修复 workspace 清单，再重新确认同一行为红灯。

- [ ] **Step 4: 实现最小配置、应用工厂和 ASGI 入口**

Create `foundation/config.py`:

```python
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DSH_COMPANY_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
```

Create `foundation/app.py`:

```python
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from dsh_company.foundation.config import Settings


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["dsh-company"]


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    app = FastAPI(title="DSH Company Service", version="0.1.0")
    app.state.settings = resolved

    @app.get("/health", response_model=HealthResponse, tags=["foundation"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="dsh-company")

    return app
```

Create `asgi.py`:

```python
from dsh_company.foundation.app import create_app

app = create_app()
```

Create `api/openapi.py`:

```python
import json

from dsh_company.foundation.app import create_app


def main() -> None:
    print(json.dumps(create_app().openapi(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 运行聚焦测试与静态检查**

Run:

```powershell
uv run pytest apps/company-service/tests/foundation -q
uv run ruff check apps/company-service/src apps/company-service/tests
uv run pyright
```

Expected: all commands exit 0; health tests pass; Pyright reports 0 errors.

- [ ] **Step 6: Commit**

```powershell
git add pyproject.toml uv.lock apps/company-service
git commit -m "feat: add minimal company service foundation"
```

### Task 3: 用 TDD 建立可构建的 DSH Host/Client 插件空壳

**Files:**

- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `apps/dsh-company-plugin/package.json`
- Create: `apps/dsh-company-plugin/cordis.patch.yml`
- Create: `apps/dsh-company-plugin/tsconfig.json`
- Create: `apps/dsh-company-plugin/tsconfig.host.json`
- Create: `apps/dsh-company-plugin/tsconfig.client.json`
- Create: `apps/dsh-company-plugin/tsdown.config.ts`
- Create: `apps/dsh-company-plugin/vitest.config.ts`
- Create: `apps/dsh-company-plugin/src/index.ts`
- Create: `apps/dsh-company-plugin/src/client/index.ts`
- Create: `apps/dsh-company-plugin/tests/bundle-manifest.spec.ts`
- Generate: `pnpm-lock.yaml`

- [ ] **Step 1: 创建 Node workspace 与插件清单**

Root `package.json` must expose these scripts and no business scripts:

```json
{
  "name": "dsh-company-workspace",
  "version": "0.1.0",
  "private": true,
  "packageManager": "pnpm@11.7.0",
  "engines": { "node": ">=22.19.0", "pnpm": ">=11.0.0" },
  "scripts": {
    "build": "pnpm --filter @dsh/company-plugin build",
    "typecheck": "pnpm --filter @dsh/company-plugin typecheck",
    "test": "pnpm --filter @dsh/company-plugin test",
    "check": "pnpm run contracts:test && pnpm --filter @dsh/company-plugin check",
    "contracts:test": "node --test packages/contracts/tests/contract-tools.test.mjs",
    "contracts:generate": "node packages/contracts/scripts/generate-types.mjs --input packages/contracts/openapi/openapi.json --output apps/dsh-company-plugin/src/contracts/generated/openapi.ts"
  },
  "devDependencies": { "openapi-typescript": "7.13.0" }
}
```

Create `pnpm-workspace.yaml`:

```yaml
packages:
  - apps/dsh-company-plugin
```

Create `apps/dsh-company-plugin/package.json`:

```json
{
  "name": "@dsh/company-plugin",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "main": "dist/index.mjs",
  "types": "lib/types/index.d.ts",
  "exports": {
    ".": { "types": "./lib/types/index.d.ts", "default": "./dist/index.mjs" },
    "./client": { "types": "./lib/types/client/index.d.ts", "default": "./dist/client.js" },
    "./cordis.patch.yml": "./cordis.patch.yml",
    "./package.json": "./package.json"
  },
  "files": ["dist", "lib/types/**/*.d.ts", "cordis.patch.yml"],
  "dsh": {
    "bundle": { "patch": "./cordis.patch.yml" },
    "client": { "platform": "web", "inject": ["@deepseek-ai/dsh-client-runtime"] }
  },
  "engines": { "node": ">=22.19.0", "pnpm": ">=11.0.0" },
  "scripts": {
    "build:types:host": "tsc -p tsconfig.host.json",
    "build:host": "pnpm run build:types:host && tsdown --env.DSH_BUILD_FACE=host",
    "build:types:client": "tsc -p tsconfig.client.json",
    "build:client": "pnpm run build:types:client && tsdown --env.DSH_BUILD_FACE=client",
    "build": "pnpm run build:host && pnpm run build:client",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit",
    "check": "pnpm typecheck && pnpm build && pnpm test"
  },
  "peerDependencies": {
    "@deepseek-ai/cordis": "*",
    "@deepseek-ai/dsh-client-runtime": "*"
  },
  "devDependencies": {
    "@deepseek-ai/cordis": "4.0.1",
    "@deepseek-ai/dsh-client-runtime": "link:../../vendor/deepseek-harness/packages/client/runtime",
    "@types/node": "^22.20.0",
    "tsdown": "0.21.0",
    "typescript": "^5.9.3",
    "vitest": "^4.1.8"
  }
}
```

This intentionally excludes React, credentials, remotes, locale, layout, sidebar, Schemastery and Zod until a real consumer exists.

Create `tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2024",
    "lib": ["ES2024", "DOM", "DOM.Iterable"],
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "noEmit": true,
    "types": ["node", "vitest/globals"],
    "skipLibCheck": true
  },
  "include": ["src/**/*.ts", "tests/**/*.ts", "vitest.config.ts", "tsdown.config.ts"]
}
```

Create `tsconfig.host.json`:

```json
{
  "extends": "./tsconfig.json",
  "compilerOptions": {
    "noEmit": false,
    "declaration": true,
    "outDir": "./lib/types",
    "rootDir": "./src",
    "types": ["node"]
  },
  "include": ["src/index.ts"],
  "exclude": ["src/client/**/*", "tests/**/*"]
}
```

Create `tsconfig.client.json`:

```json
{
  "extends": "./tsconfig.json",
  "compilerOptions": {
    "noEmit": false,
    "declaration": true,
    "outDir": "./lib/types",
    "rootDir": "./src"
  },
  "include": ["src/client/**/*.ts", "src/contracts/**/*.ts"],
  "exclude": ["tests/**/*"]
}
```

Create `vitest.config.ts`:

```typescript
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: { include: ['tests/**/*.spec.ts'], restoreMocks: true },
})
```

Create a no-config patch:

```yaml
- insert:
    - id: dsh-company
      name: '@dsh/company-plugin'
```

- [ ] **Step 2: 写出会失败的插件身份与 bundle 测试**

Create `tests/bundle-manifest.spec.ts`:

```typescript
import { readFile } from 'node:fs/promises'

import { describe, expect, it } from 'vitest'

describe('DSH Company plugin bundle', () => {
  it('declares independent host and client exports', async () => {
    const manifest = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))

    expect(manifest.name).toBe('@dsh/company-plugin')
    expect(manifest.exports['.'].default).toBe('./dist/index.mjs')
    expect(manifest.exports['./client'].default).toBe('./dist/client.js')
    expect(manifest.dsh.bundle.patch).toBe('./cordis.patch.yml')
  })

  it('builds a DSH client module-loader bundle', async () => {
    const bundle = await readFile(new URL('../dist/client.js', import.meta.url), 'utf8')

    expect(bundle).toContain('window.__ModuleLoader__.load')
    expect(bundle).toContain('@dsh/company-plugin')
  })
})
```

- [ ] **Step 3: 运行测试并确认红灯原因正确**

After installing vendor and root dependencies:

```powershell
pnpm --dir vendor/deepseek-harness install --frozen-lockfile
pnpm install
pnpm --filter @dsh/company-plugin test -- bundle-manifest.spec.ts
```

Expected: the manifest assertion may pass, but the bundle test fails with missing `dist/client.js`; no业务 API failure should appear.

- [ ] **Step 4: 实现无业务逻辑的 Host/Client 入口和构建配置**

Create `src/index.ts`:

```typescript
import type { Context } from '@deepseek-ai/cordis'

export const name = 'dsh-company'
export const inject: readonly string[] = []

export function apply(_ctx: Context): void {}

export default { name, inject, apply }
```

Create `src/client/index.ts`:

```typescript
import type { ClientContext } from '@deepseek-ai/dsh-client-runtime/client'

export const inject: readonly string[] = []

export async function apply(_ctx: ClientContext): Promise<() => Promise<void>> {
  return async () => {}
}
```

Create `tsdown.config.ts` without the old CSS plugin:

```typescript
import { defineConfig } from 'tsdown'

export default defineConfig(({ env }) => {
  const client = env?.DSH_BUILD_FACE === 'client'
  return {
    entry: client ? { client: 'lib/types/client/index.js' } : ['lib/types/index.js'],
    outDir: 'dist',
    format: client ? ['cjs'] : ['esm'],
    platform: client ? 'browser' : 'node',
    target: 'es2024',
    dts: false,
    clean: !client,
    ...(client ? {
      outputOptions: {
        entryFileNames: 'client.js',
        banner: 'window.__ModuleLoader__.load({ id: "@dsh/company-plugin", factory: (require) => {',
        footer: 'return module.exports; } });',
        intro: 'var module = { exports: {} }; var exports = module.exports;',
      },
    } : {}),
  }
})
```

The host build remains ESM, the client build remains browser CJS, and `build` must run type emission before tsdown for each face.

- [ ] **Step 5: 构建并转绿**

Run:

```powershell
pnpm --dir vendor/deepseek-harness run build:lib
pnpm --filter @dsh/company-plugin typecheck
pnpm --filter @dsh/company-plugin build
pnpm --filter @dsh/company-plugin test -- bundle-manifest.spec.ts
pnpm install --lockfile-only
```

Expected: all commands exit 0; `dist/index.mjs`, `dist/client.js` and declaration files exist; the focused test passes; `pnpm-lock.yaml` is created.

- [ ] **Step 6: Commit**

```powershell
git add package.json pnpm-workspace.yaml pnpm-lock.yaml apps/dsh-company-plugin
git commit -m "feat: scaffold DSH company plugin faces"
```

### Task 4: 用 TDD 建立 OpenAPI 契约生成与兼容性检查

**Files:**

- Create: `packages/contracts/README.md`
- Create: `packages/contracts/fixtures/minimal.openapi.json`
- Create: `packages/contracts/fixtures/breaking/field-removed.openapi.json`
- Create: `packages/contracts/fixtures/breaking/enum-changed.openapi.json`
- Create: `packages/contracts/scripts/generate-types.mjs`
- Create: `packages/contracts/scripts/check-compatibility.mjs`
- Create: `packages/contracts/scripts/capture-company-service-openapi.mjs`
- Create: `packages/contracts/tests/contract-tools.test.mjs`
- Generate: `packages/contracts/openapi/openapi.json`
- Generate: `packages/contracts/openapi/source-revision.json`
- Generate: `apps/dsh-company-plugin/src/contracts/generated/openapi.ts`
- Modify: `package.json`

- [ ] **Step 1: 写出契约工具红灯测试与领域无关 fixture**

Create `fixtures/minimal.openapi.json`:

```json
{
  "openapi": "3.1.0",
  "info": { "title": "DSH Company fixture", "version": "0.1.0" },
  "paths": {
    "/health": {
      "get": {
        "responses": {
          "200": {
            "description": "Healthy",
            "content": {
              "application/json": {
                "schema": { "$ref": "#/components/schemas/HealthResponse" }
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "HealthResponse": {
        "type": "object",
        "required": ["status", "service"],
        "properties": {
          "status": { "type": "string", "enum": ["ok"] },
          "service": { "type": "string", "enum": ["dsh-company"] }
        }
      }
    }
  }
}
```

Create `breaking/field-removed.openapi.json` from this exact document by removing `service` from both `required` and `properties`. Create `breaking/enum-changed.openapi.json` from the exact document by changing only `status.enum` from `["ok"]` to `["healthy"]`.

Adapt the fixed source test file `multi-agent@2330adb:packages/contracts/tests/contract-tools.test.mjs` so it asserts only:

1. generated TypeScript contains `/health`, `HealthResponse`, `status: "ok"` and `service: "dsh-company"`;
2. generating twice produces identical text;
3. field removal and enum change exit 1;
4. service capture writes a snapshot and exactly this provenance object:

```json
{
  "api_commit": "0123456789abcdef0123456789abcdef01234567",
  "source_kind": "FastAPI app.openapi()"
}
```

Run:

```powershell
pnpm run contracts:test
```

Expected: tests fail because the three scripts do not exist.

- [ ] **Step 2: 迁移最小生成器与兼容性比较器**

Port these two fixed-source files without product-specific additions:

- `multi-agent@2330adb:packages/contracts/scripts/generate-types.mjs`
- `multi-agent@2330adb:packages/contracts/scripts/check-compatibility.mjs`

Keep their CLI contracts and recursive schema comparison. Do not port Task/Event fixture names or extra compatibility cases not represented by the new fixture.

- [ ] **Step 3: 实现 Company Service OpenAPI capture，不生成哈希**

Create `capture-company-service-openapi.mjs` with the same argument parser shape as the old capture tool. It must:

```javascript
const source = execFileSync(
  process.platform === 'win32' ? 'uv.exe' : 'uv',
  ['run', 'python', '-m', 'dsh_company.api.openapi'],
  { cwd: repositoryRoot, encoding: 'utf8' },
)
JSON.parse(source)
writeFileSync(outputPath, `${source.trim()}\n`, 'utf8')
writeFileSync(
  revisionPath,
  `${JSON.stringify({ api_commit: apiCommit, source_kind: 'FastAPI app.openapi()' }, null, 2)}\n`,
  'utf8',
)
```

Validate `apiCommit` with the existing hexadecimal revision rule. Do not import `node:crypto` and do not add a checksum field because no consumer changes behavior from it.

- [ ] **Step 4: 运行契约测试并确认转绿**

Run:

```powershell
pnpm run contracts:test
```

Expected: generator determinism, both breaking fixtures and live service capture all pass.

- [ ] **Step 5: 捕获权威契约并生成 TypeScript**

Add root script:

```json
"contracts:capture": "node packages/contracts/scripts/capture-company-service-openapi.mjs --output packages/contracts/openapi/openapi.json --revision-output packages/contracts/openapi/source-revision.json"
```

Run:

```powershell
$apiCommit = git rev-parse HEAD
pnpm run contracts:capture -- --api-commit $apiCommit
pnpm run contracts:generate
pnpm --filter @dsh/company-plugin typecheck
```

Expected: all commands exit 0; snapshot contains `/health`; source revision contains the current commit and `source_kind` only; generated TypeScript typechecks.

- [ ] **Step 6: Commit**

```powershell
git add package.json packages/contracts apps/dsh-company-plugin/src/contracts/generated/openapi.ts
git commit -m "feat: establish company OpenAPI contract pipeline"
```

### Task 5: 用 TDD 建立公共检查命令和跨平台 CI

**Files:**

- Create: `tools/__init__.py`
- Create: `tools/check.py`
- Create: `tests/system/pytest.ini`
- Create: `tests/system/tests/test_repository_layout.py`
- Create: `tests/system/tests/test_public_check.py`
- Create: `.github/workflows/ci.yml`
- Modify: `package.json`
- Modify: `CONTRIBUTING.md`

- [ ] **Step 1: 写出会失败的仓库布局与检查计划测试**

`test_repository_layout.py` must use `tomllib`/`json` to assert:

- Python root depends on `dsh-company-service` and includes only `apps/company-service` as uv member;
- pnpm includes only `apps/dsh-company-plugin`;
- plugin package is `@dsh/company-plugin`;
- `.gitmodules` points to `vendor/deepseek-harness`;
- `docs/development/multi-agent-reuse.md` records both fixed source commits.

`test_public_check.py` must import `tools.check.check_commands()` and assert this exact behavior order:

```python
[
    "uv lock --check",
    "ruff check",
    "pyright",
    "pytest apps/company-service/tests tests/system/tests -q",
    "pnpm --dir vendor/deepseek-harness run build:lib",
    "pnpm run check",
]
```

Resolve Windows launcher suffixes before comparing command stems.

Run:

```powershell
uv run pytest tests/system/tests -q
```

Expected: `test_repository_layout.py` passes and `test_public_check.py` fails because `tools.check` does not exist.

- [ ] **Step 2: 实现单一公共门禁入口**

Adapt `multi-agent@2330adb:tools/check.py` with these exact path changes:

- Ruff: `apps/company-service/src`, `apps/company-service/tests`, `tests/system`, `tools`;
- Pytest: `apps/company-service/tests` and `tests/system/tests` in one command;
- remove the old M7-only system gate;
- retain the DSH vendor library build;
- retain `pnpm run check`;
- all subprocesses use repository root and stop at the first nonzero exit code.

Keep the known-safe environment allowlist so the public gate proves it does not depend on a developer credential. Set `CI=true`; do not inspect or log excluded environment names or values.

- [ ] **Step 3: 运行聚焦测试并确认转绿**

Run:

```powershell
uv run pytest tests/system/tests -q
```

Expected: layout and check-plan tests pass.

- [ ] **Step 4: 添加 Windows/Ubuntu CI**

Create `.github/workflows/ci.yml` from the fixed source workflow with:

- `windows-latest` and `ubuntu-latest` matrix;
- recursive submodule checkout;
- Python 3.13, uv 0.8.13, Node 22.19.0, pnpm 11.7.0;
- `uv sync --frozen --all-packages --all-groups`;
- vendor then root `pnpm install --frozen-lockfile`;
- final `python tools/check.py`.

Do not add provider secrets, cache keys, deployment or release jobs.

- [ ] **Step 5: 运行完整公共门禁**

Run:

```powershell
python tools/check.py
git diff --check
```

Expected: check script prints every command and ends with `[check] all keyless gates passed`; `git diff --check` has no output.

- [ ] **Step 6: Commit**

```powershell
git add tools tests/system .github/workflows/ci.yml CONTRIBUTING.md package.json
git commit -m "ci: add cross-platform public verification gate"
```

### Task 6: 完成开发者文档与实际启动验收

**Files:**

- Modify: `README.md`
- Modify: `docs/README.md`
- Create: `docs/development/contracts.md`
- Create: `.env.example`

- [ ] **Step 1: 写清真实可用的本地流程**

README and contributing docs must document only commands already proven by Tasks 1–5:

```powershell
git submodule update --init --recursive
uv sync --all-packages --all-groups
pnpm --dir vendor/deepseek-harness install --frozen-lockfile
pnpm --dir vendor/deepseek-harness run build:lib
pnpm install --frozen-lockfile
python tools/check.py
uv run uvicorn dsh_company.asgi:app --host 127.0.0.1 --port 8000
```

`.env.example` contains only `DSH_COMPANY_HOST=127.0.0.1`, `DSH_COMPANY_PORT=8000` and `DSH_COMPANY_LOG_LEVEL=INFO`. It must not contain model/provider credentials because Phase 0 does not call DSH.

`docs/development/contracts.md` must define: FastAPI owns schemas, committed OpenAPI is the transport snapshot, generated TypeScript is never hand-edited, capture records the API commit, compatibility changes require an explicit review. Link it from `docs/README.md`.

- [ ] **Step 2: 运行真实服务健康检查**

Run with a hidden background process on Windows:

```powershell
$service = Start-Process uv -ArgumentList 'run','uvicorn','dsh_company.asgi:app','--host','127.0.0.1','--port','8000' -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru
try {
  $response = $null
  for ($attempt = 0; $attempt -lt 30 -and $null -eq $response; $attempt++) {
    try { $response = Invoke-RestMethod http://127.0.0.1:8000/health } catch { Start-Sleep -Milliseconds 250 }
  }
  if ($null -eq $response) { throw 'Company Service did not become healthy' }
  $response | ConvertTo-Json -Compress
} finally {
  Stop-Process -Id $service.Id -ErrorAction SilentlyContinue
}
```

Expected: `{"status":"ok","service":"dsh-company"}` and port 8000 is released in `finally`.

- [ ] **Step 3: 做一次有明确处置的范围检查**

Run:

```powershell
rg -n "dsh_multi_agent|@dsh/multi-agent-plugin|crewai|worktree|Delivery" apps packages tools .github pyproject.toml package.json pnpm-workspace.yaml
```

Expected: no matches. Any match means the Phase 0 implementation contains old业务耦合 and must be removed before proceeding.

- [ ] **Step 4: 最终验证**

Run:

```powershell
python tools/check.py
git diff --check
git status --short
git log --oneline -6
```

Expected: all gates pass; diff check is silent; status shows only the intended documentation files for this task before commit; history shows one focused commit per prior task.

- [ ] **Step 5: Commit**

```powershell
git add README.md docs .env.example
git commit -m "docs: document repository foundation workflow"
```

## Phase 0 完成定义

只有以下事实全部成立，才能开始 DSH 公共能力 Spike：

- fresh clone + recursive submodule can install from committed lockfiles;
- `python tools/check.py` passes without provider credentials on Windows and Ubuntu CI;
- Company Service responds with the documented health payload;
- Host and Client bundles build from the independent `@dsh/company-plugin` package;
- OpenAPI snapshot and generated TypeScript are reproducible and compatibility-tested;
- no Company Domain、数据库、CrewAI、Memory、Git collaboration or old product DTO has entered the new repository;
- `multi-agent` remains untouched and usable as the future software-development plugin source.
