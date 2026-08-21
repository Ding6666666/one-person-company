# Company strategy benchmark fixtures

`tasks.jsonl` is the versioned `company-v1` deterministic task set used to compare complete
DSH Company strategies. Every row declares its own allowed strategies and token, duration,
and user-intervention budgets. The fixtures contain no provider credentials or third-party
benchmark text.

Install the evaluation tooling separately from production dependencies:

```powershell
uv sync --group evaluation
uv run --group evaluation pytest apps/company-service/tests/evaluation -q
```

The adapter targets the installed public MASEval 0.5.1 API: it subclasses `AgentAdapter`,
passes `(agent_instance, name)` to its constructor, implements `_run_agent`, and returns an
actual `MessageHistory` from `get_messages`. It invokes the complete Company client's
`run_and_wait(workspace_id, strategy, objective)` operation. Only closed system outcome fields
(`status`, `work_id`, `task_success`, and `metrics`) enter the benchmark result or MASEval
message history; raw model output and DSH transcripts are never retained.

Evaluation runs and their metadata are benchmark artifacts. They are not written to Company
production tables. Real-provider comparison is intentionally outside this keyless fixture set.
