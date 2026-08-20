# Phase 1B DSH Public Capability Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 DSH 固定源码和 keyless 模型端点验证 Employee 所需的 Session、事件、恢复、隔离和取消能力，并生成后续产品代码必须遵守的能力矩阵。

**Architecture:** Spike 通过公开 `deepseek_harness.DeepSeekHarness` 驱动真实 DSH JSON-RPC runtime，不创建 Company Domain 或长期兼容层。所有能力都输出 `supported`、`constrained` 或 `not_exposed`；后续 Gateway 只能依赖报告中已验证的语义。

**Tech Stack:** Python 3.13、DeepSeek Harness Python SDK 与 runtime source、ThreadingHTTPServer keyless SSE endpoint、Pytest、Pydantic。

---

## 目标结构

```text
apps/company-service/src/dsh_company/dsh_gateway/
├── capability_report.py   # 稳定的能力报告类型
├── keyless_endpoint.py    # 测试专用 OpenAI-compatible SSE endpoint
├── spike.py               # DSH 公共能力探针与 CLI
└── spike_runtime.py       # 每个 Session/Attempt 的公开 SDK 驱动
apps/company-service/tests/dsh_gateway/
├── test_public_sdk_contract.py
├── test_spike_runtime.py
└── test_spike_report.py
docs/development/dsh-capability-matrix.md
```

### Task 1: 安装固定 DSH SDK 并增加 Spike 配置

**Files:**

- Modify: `apps/company-service/pyproject.toml`
- Modify: `apps/company-service/src/dsh_company/foundation/config.py`
- Modify: `apps/company-service/tests/foundation/test_config.py`
- Modify: `uv.lock`

- [ ] **Step 1: 写失败的 DSH 配置测试**

Append:

```python
def test_settings_expose_only_public_dsh_runtime_inputs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DSH_COMPANY_DSH_PROVIDER", "test-provider")
    monkeypatch.setenv("DSH_COMPANY_DSH_MODEL", "test-model")
    monkeypatch.setenv("DSH_COMPANY_SESSION_ROOT", str(tmp_path / "sessions"))

    settings = Settings()

    assert settings.dsh_provider == "test-provider"
    assert settings.dsh_model == "test-model"
    assert settings.session_root == tmp_path / "sessions"
    assert settings.dsh_request_timeout_seconds == 60.0
    assert settings.dsh_shutdown_timeout_seconds == 10.0
```

- [ ] **Step 2: 确认红灯**

Run: `uv run pytest apps/company-service/tests/foundation/test_config.py -q`

Expected: FAIL because `Settings` has no `dsh_provider`.

- [ ] **Step 3: 添加 SDK 依赖与配置**

Add service dependency and local sources:

```toml
dependencies = [
  "deepseek-harness-sdk==0.0.0.dev0",
  "fastapi==0.141.1",
  "pydantic==2.12.5",
  "pydantic-settings==2.14.2",
  "structlog==25.5.0",
  "uvicorn==0.52.3",
]

[tool.uv.sources]
deepseek-harness-sdk = { path = "../../vendor/deepseek-harness/python/sdk", editable = true }
deepseek-harness-runtime-bin = { path = "../../vendor/deepseek-harness/python/sdk-runtime", editable = true }
```

Add settings:

```python
from pathlib import Path

dsh_provider: str = "deepseek-official"
dsh_model: str = "deepseek-v4-flash"
session_root: Path = Path("../dsh-company-data/sessions")
dsh_request_timeout_seconds: float = 60.0
dsh_shutdown_timeout_seconds: float = 10.0
```

Run:

```powershell
uv lock
uv sync --all-packages --all-groups
uv run pytest apps/company-service/tests/foundation/test_config.py -q
```

Expected: commands exit 0 and the new test passes.

- [ ] **Step 4: Commit**

```powershell
git add apps/company-service/pyproject.toml apps/company-service/src/dsh_company/foundation/config.py apps/company-service/tests/foundation/test_config.py uv.lock
git commit -m "spike: add fixed DSH SDK dependency"
```

### Task 2: 固定能力报告类型与公开 SDK 契约

**Files:**

- Create: `apps/company-service/src/dsh_company/dsh_gateway/__init__.py`
- Create: `apps/company-service/src/dsh_company/dsh_gateway/capability_report.py`
- Create: `apps/company-service/tests/dsh_gateway/test_public_sdk_contract.py`
- Create: `apps/company-service/tests/dsh_gateway/test_spike_report.py`

- [ ] **Step 1: 写公开签名和报告序列化测试**

```python
import inspect

from deepseek_harness import DeepSeekHarness, RunResult, Session

from dsh_company.dsh_gateway.capability_report import (
    CapabilityObservation,
    CapabilityState,
    DshCapabilityReport,
)


def test_current_public_sdk_exposes_the_session_boundary_we_use() -> None:
    assert "session_id" in inspect.signature(DeepSeekHarness.start_session).parameters
    assert "session_id" in inspect.signature(DeepSeekHarness.run).parameters
    assert "on_notification" in inspect.signature(Session.run).parameters
    assert set(RunResult.__dataclass_fields__) >= {
        "session_id", "final_response", "finish_reason", "events", "notifications"
    }


def test_capability_report_is_closed_and_serializable() -> None:
    report = DshCapabilityReport(
        dsh_revision="2db6ebd58523d14dca278e366ea0eb40499702b9",
        observations=(
            CapabilityObservation(
                capability="session.create",
                state=CapabilityState.SUPPORTED,
                evidence="public SDK returned the requested session id",
            ),
        ),
    )

    assert report.model_dump(mode="json")["observations"][0]["state"] == "supported"
```

- [ ] **Step 2: 确认红灯**

Run: `uv run pytest apps/company-service/tests/dsh_gateway/test_public_sdk_contract.py apps/company-service/tests/dsh_gateway/test_spike_report.py -q`

Expected: collection FAIL because `capability_report` does not exist.

- [ ] **Step 3: 实现封闭报告类型**

```python
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class CapabilityState(StrEnum):
    SUPPORTED = "supported"
    CONSTRAINED = "constrained"
    NOT_EXPOSED = "not_exposed"


class CapabilityObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    capability: str
    state: CapabilityState
    evidence: str


class DshCapabilityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dsh_revision: str
    observations: tuple[CapabilityObservation, ...]

    def by_name(self) -> dict[str, CapabilityObservation]:
        return {item.capability: item for item in self.observations}
```

- [ ] **Step 4: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/dsh_gateway/test_public_sdk_contract.py apps/company-service/tests/dsh_gateway/test_spike_report.py -q
git add apps/company-service/src/dsh_company/dsh_gateway apps/company-service/tests/dsh_gateway
git commit -m "spike: define DSH capability evidence contract"
```

Expected: tests pass and commit succeeds.

### Task 3: 用真实 DSH runtime 和 keyless endpoint 验证两个 Session

**Files:**

- Create: `apps/company-service/src/dsh_company/dsh_gateway/keyless_endpoint.py`
- Create: `apps/company-service/src/dsh_company/dsh_gateway/spike_runtime.py`
- Create: `apps/company-service/tests/dsh_gateway/test_spike_runtime.py`

- [ ] **Step 1: 写两个 Session 独立执行测试**

```python
from dsh_company.dsh_gateway.keyless_endpoint import KeylessModelEndpoint
from dsh_company.dsh_gateway.spike_runtime import DshSpikeRuntime


def test_two_employee_sessions_execute_without_crossing_context(tmp_path) -> None:
    with KeylessModelEndpoint() as endpoint:
        runtime = DshSpikeRuntime(
            base_url=endpoint.base_url,
            session_root=tmp_path / "sessions",
            working_directory=tmp_path,
        )
        alpha = runtime.run("employee-alpha", "remember ALPHA_ONLY")
        beta = runtime.run("employee-beta", "remember BETA_ONLY")

    assert alpha.session_id == "employee-alpha"
    assert beta.session_id == "employee-beta"
    assert alpha.finish_reason == "completed"
    assert beta.finish_reason == "completed"
    assert endpoint.request_for("employee-alpha").contains("ALPHA_ONLY")
    assert not endpoint.request_for("employee-alpha").contains("BETA_ONLY")
    assert endpoint.request_for("employee-beta").contains("BETA_ONLY")
    assert not endpoint.request_for("employee-beta").contains("ALPHA_ONLY")
```

- [ ] **Step 2: 确认红灯**

Run: `uv run pytest apps/company-service/tests/dsh_gateway/test_spike_runtime.py::test_two_employee_sessions_execute_without_crossing_context -q`

Expected: collection FAIL because the endpoint and runtime modules do not exist.

- [ ] **Step 3: 实现 keyless SSE endpoint**

Implement `KeylessModelEndpoint` as a context manager around `ThreadingHTTPServer(("127.0.0.1", 0), handler)`. The handler must:

```python
def do_POST(self) -> None:
    length = int(self.headers.get("content-length", "0"))
    body = json.loads(self.rfile.read(length).decode("utf-8"))
    session_marker = next(
        text
        for message in body["messages"]
        for block in message.get("content", [])
        if isinstance(block, dict)
        if (text := str(block.get("text", ""))).startswith("remember ")
    )
    self.server.requests.append(ModelRequest(body=body, marker=session_marker))
    self.send_response(200)
    self.send_header("content-type", "text/event-stream")
    self.end_headers()
    chunks = (
        'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}\n\n',
        f'data: {{"choices":[{{"delta":{{"content":"stored {session_marker}"}}}}]}}\n\n',
        'data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":3}}\n\n',
        'data: [DONE]\n\n',
    )
    for chunk in chunks:
        self.wfile.write(chunk.encode("utf-8"))
```

`request_for(marker)` returns a `ModelRequest` whose `contains(text)` performs JSON-string containment on its captured body. The endpoint uses the fixed header `Bearer dsh-company-spike-key`; the value exists only inside the local test process and is not written to logs or files.

- [ ] **Step 4: 实现公开 SDK 驱动**

```python
from pathlib import Path

from deepseek_harness import DeepSeekHarness, RunResult


class DshSpikeRuntime:
    def __init__(self, *, base_url: str, session_root: Path, working_directory: Path) -> None:
        self._base_url = base_url
        self._session_root = session_root
        self._working_directory = working_directory

    def run(self, session_id: str, prompt: str) -> RunResult:
        with DeepSeekHarness(
            provider="deepseek-official",
            model="dsh-company-spike-model",
            cwd=str(self._working_directory),
            session_root=str(self._session_root),
            base_url=self._base_url,
            api_key="dsh-company-spike-key",
            request_timeout_seconds=20,
            shutdown_timeout_seconds=2,
        ) as harness:
            return harness.run(prompt, session_id=session_id)
```

- [ ] **Step 5: 构建 runtime 并转绿**

```powershell
pnpm --dir vendor/deepseek-harness run build:lib
uv run pytest apps/company-service/tests/dsh_gateway/test_spike_runtime.py::test_two_employee_sessions_execute_without_crossing_context -q
```

Expected: PASS and the endpoint receives one request per Session with no crossed marker.

- [ ] **Step 6: Commit**

```powershell
git add apps/company-service/src/dsh_company/dsh_gateway apps/company-service/tests/dsh_gateway/test_spike_runtime.py
git commit -m "spike: prove independent DSH employee sessions"
```

### Task 4: 验证重启恢复和 Session 连续上下文

**Files:**

- Modify: `apps/company-service/src/dsh_company/dsh_gateway/keyless_endpoint.py`
- Modify: `apps/company-service/tests/dsh_gateway/test_spike_runtime.py`

- [ ] **Step 1: 写恢复测试**

```python
def test_same_session_recalls_prior_turn_after_runtime_restart(tmp_path) -> None:
    with KeylessModelEndpoint() as endpoint:
        first_runtime = DshSpikeRuntime(
            base_url=endpoint.base_url,
            session_root=tmp_path / "sessions",
            working_directory=tmp_path,
        )
        first_runtime.run("employee-alpha", "remember ALPHA_ONLY")

        second_runtime = DshSpikeRuntime(
            base_url=endpoint.base_url,
            session_root=tmp_path / "sessions",
            working_directory=tmp_path,
        )
        recalled = second_runtime.run("employee-alpha", "recall the employee marker")

    assert recalled.session_id == "employee-alpha"
    second_request = endpoint.requests[-1]
    assert second_request.contains("ALPHA_ONLY")
    assert second_request.contains("recall the employee marker")
```

- [ ] **Step 2: 确认红灯**

Run the new test. Expected: FAIL because the endpoint currently requires every request to contain a new `remember` marker.

- [ ] **Step 3: 让 endpoint 支持恢复轮次**

Change marker selection to read the latest `remember ` content when present, otherwise use the marker already present in the request history. Return a response containing that marker. Do not add a Company-side memory store.

```python
markers = [text for text in all_text_blocks(body) if "ALPHA_ONLY" in text or "BETA_ONLY" in text]
marker = "ALPHA_ONLY" if any("ALPHA_ONLY" in text for text in markers) else "BETA_ONLY"
```

- [ ] **Step 4: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/dsh_gateway/test_spike_runtime.py -q
git add apps/company-service/src/dsh_company/dsh_gateway/keyless_endpoint.py apps/company-service/tests/dsh_gateway/test_spike_runtime.py
git commit -m "spike: prove DSH session continuity after restart"
```

Expected: both isolation and restart tests pass.

### Task 5: 固定取消与未暴露能力的真实语义

**Files:**

- Modify: `apps/company-service/src/dsh_company/dsh_gateway/spike_runtime.py`
- Modify: `apps/company-service/tests/dsh_gateway/test_public_sdk_contract.py`
- Modify: `apps/company-service/tests/dsh_gateway/test_spike_runtime.py`

- [ ] **Step 1: 写取消约束测试**

```python
def test_attempt_cancel_is_harness_close_not_session_observe(tmp_path) -> None:
    runtime = RecordingHarnessRuntime(tmp_path)
    handle = runtime.start("employee-alpha", "wait for cancellation")

    result = handle.cancel()

    assert result.requested is True
    assert result.runtime_closed is True
    assert runtime.close_calls == 1


def test_public_sdk_does_not_claim_unavailable_surfaces() -> None:
    assert not hasattr(DeepSeekHarness, "list_capabilities")
    assert not hasattr(DeepSeekHarness, "observe")
    assert not hasattr(Session, "cancel")
    assert not hasattr(Session, "write_memory")
```

`RecordingHarnessRuntime` is a test double for lifecycle order only; Session execution and persistence remain covered by the real runtime tests.

- [ ] **Step 2: 确认红灯**

Run the two tests. Expected: lifecycle test FAIL because no attempt handle exists; public absence test passes and documents the current boundary.

- [ ] **Step 3: 实现最小 Attempt handle**

```python
@dataclass(frozen=True, slots=True)
class SpikeCancelResult:
    requested: bool
    runtime_closed: bool


class SpikeAttemptHandle:
    def __init__(self, harness: DeepSeekHarness) -> None:
        self._harness = harness
        self._closed = False

    def cancel(self) -> SpikeCancelResult:
        if not self._closed:
            self._harness.close()
            self._closed = True
        return SpikeCancelResult(requested=True, runtime_closed=True)
```

Each handle owns exactly one Harness. Never share a Harness between concurrently cancellable attempts.

- [ ] **Step 4: 转绿并提交**

```powershell
uv run pytest apps/company-service/tests/dsh_gateway -q
git add apps/company-service/src/dsh_company/dsh_gateway apps/company-service/tests/dsh_gateway
git commit -m "spike: record constrained DSH cancellation semantics"
```

### Task 6: 生成正式能力矩阵并加入公共门禁

**Files:**

- Create: `apps/company-service/src/dsh_company/dsh_gateway/spike.py`
- Create: `docs/development/dsh-capability-matrix.md`
- Modify: `docs/README.md`
- Modify: `tools/check.py`
- Modify: `tests/system/tests/test_public_check.py`

- [ ] **Step 1: 写报告内容测试**

```python
def test_report_contains_every_gateway_decision() -> None:
    report = build_capability_report()
    observations = report.by_name()

    assert observations["session.create"].state is CapabilityState.SUPPORTED
    assert observations["session.resume"].state is CapabilityState.SUPPORTED
    assert observations["session.events"].state is CapabilityState.SUPPORTED
    assert observations["session.cancel"].state is CapabilityState.CONSTRAINED
    assert observations["attempt.observe"].state is CapabilityState.NOT_EXPOSED
    assert observations["capability.list"].state is CapabilityState.NOT_EXPOSED
    assert observations["memory.provider"].state is CapabilityState.NOT_EXPOSED
    assert observations["identity.agent"].state is CapabilityState.CONSTRAINED
```

- [ ] **Step 2: 确认红灯并实现报告**

Run: `uv run pytest apps/company-service/tests/dsh_gateway/test_spike_report.py -q`

Expected: FAIL because `build_capability_report` is absent.

Implement observations with exact evidence:

- `session.create`: requested ID returned by public SDK;
- `session.resume`: prior turn appeared after a new runtime process used the same root/ID;
- `session.events`: root events and notifications returned;
- `session.cancel`: only an Attempt-owned Harness close is exposed;
- `attempt.observe`: no public SDK method;
- `capability.list`: no public SDK method;
- `memory.provider`: no independent API; Session continuity only;
- `identity.agent`: AgentRegistry contract says Agent ID equals Session ID, Python SDK exposes only Session ID.

- [ ] **Step 3: 写人类可读矩阵**

`dsh-capability-matrix.md` must include the fixed DSH revision, test commands, the eight observations, and these product decisions:

```text
EmployeeAgentBinding.dsh_agent_id = EmployeeAgentBinding.dsh_session_id
one running ExecutionLink owns one DeepSeekHarness
restart of an active Attempt becomes blocked/runtime_process_lost
employee continuity uses the persistent DSH Session
Company Core does not implement a substitute memory store
runtime profiles are checked-in capability catalogs until DSH exposes discovery
```

- [ ] **Step 4: 把 keyless Spike 加入检查命令**

Add after foundation tests and before vendor/client build:

```python
(
    uv,
    "run",
    "pytest",
    "apps/company-service/tests/dsh_gateway",
    "-q",
),
```

Update the check-plan test to expect it.

- [ ] **Step 5: 完整验证**

```powershell
uv run pytest apps/company-service/tests/dsh_gateway -q
python tools/check.py
git diff --check
```

Expected: all commands exit 0; tests prove real Session isolation/restart; no provider credential is required.

- [ ] **Step 6: Commit**

```powershell
git add apps/company-service/src/dsh_company/dsh_gateway apps/company-service/tests/dsh_gateway docs tools/check.py tests/system/tests/test_public_check.py
git commit -m "docs: lock verified DSH capability matrix"
```

## Phase 1 完成定义

- Phase 1A repository plan and every Task above are committed;
- real DSH runtime reaches the keyless endpoint;
- two employee Session histories remain isolated;
- same Session resumes after runtime restart;
- cancellation is documented as Harness-scoped;
- unavailable observe/discovery/provider-memory APIs are not simulated inside Core;
- `python tools/check.py` passes without credentials.
