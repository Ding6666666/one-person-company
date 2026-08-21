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

`baseline-results.json` covers every task/strategy pair allowed by `tasks.jsonl` using the same
deterministic keyless system fixture and each row's declared budgets. The system gate calls
`dsh_company.evaluation.fixed_set.replay_fixed_task_set`, which reads `tasks.jsonl`, runs all 14
pairs through the production Company assembly and public HTTP API. Each family computes its named
checks independently from persisted Work/node/link facts plus the relevant approval, event,
employee binding, restart, or local model-request facts. It compares every closed metric other
than nondeterministic wall-clock duration; duration is replayed live and checked against the task
budget. The replay result also contains the terminal status and ephemeral Work ID as safe evidence;
Work IDs and the live-only family facts are not copied into the stable baseline. The system gate
matches ordinary Attempts one-for-one with local endpoint requests and verifies the pinned
runtime's three local retry requests per unavailable-endpoint Attempt, without retaining request
bodies, endpoint ports, session IDs, or model text.

The baseline records the fixed DSH and Company implementation revisions plus closed metrics only.
The Company revision identifies the implementation being accepted; the baseline file is committed
by the following acceptance commit. The comparison uses runtime concurrency `1` to isolate
strategy topology because the pinned public DSH runtime does not guarantee concurrent
`Session.run` completion; bounded parallel graph scheduling is covered independently by the graph
system tests. Token counts come from the keyless endpoint's fixed 5 prompt + 3 completion usage per
successfully completed node. No model text, transcript, tool argument, credential, checksum, or
digest sidecar is retained.

Restart recovery closes and rebuilds the production assembly on the same database. Company
persists `runtime_process_lost`, preserves the graph revision, and a repeated public command
explicitly creates a new Attempt. The pinned DSH does not expose cold Session resume, so the
baseline truthfully records `runtime_process_lost_retry_not_completed`. The live facts retain
whether that exact new Attempt closed as `blocked/runtime_process_lost` without a model request or
`failed/gateway_error`, either before reaching the endpoint or after the fixed local retry requests;
neither result is turned into a fabricated successful recovery or an unsupported cold resume.

The public Direct input intentionally has neither graph-node capability requirements nor a retry
budget. For Direct rows in the approval and restart families, the replay first completes the
selected Direct strategy for coverage, then drives the required governed or retryable one-node
Graph through the same public API. The live facts name that Graph path explicitly; the runner does
not pretend Direct gained fields that its published schema does not expose.
