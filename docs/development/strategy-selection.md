# Strategy selection and fixed comparison

Direct remains the global default. DSH Company does not choose a strategy from
an average score, learned rank, or a hidden framework heuristic. A caller may
select Star, Graph, or Battle explicitly, and a task family may adopt another
default only when the fixed `company-v1` comparison shows all of the following:

1. every policy, isolation, graph-integrity, and recovery invariant passes;
2. the task family's declared primary success metric improves over Direct;
3. token use, duration, and user intervention remain within that task's budgets;
4. the complete fixed task set is rerun for the proposed change.

No strategy wins globally by average score alone. Results are interpreted per
task family because parallel exploration, dependency chains, approvals, and a
single bounded action have different useful graph shapes.

## Baseline boundary

[`baseline-results.json`](../../benchmarks/company/baseline-results.json) records
only closed system metrics from the deterministic keyless fixture: success and
acceptance rates, endpoint token usage, wall-clock duration, interventions,
invalid delegations, duplicate nodes, policy violations, and a closed recovery
outcome. It contains no model text, DSH transcript, tool arguments, credentials,
or checksum sidecar. The recorded Company commit is the implementation revision
under test; the baseline document itself is the following acceptance commit.
The live gate derives every named fixture check separately from public API and
persisted Work, node, link, approval, event, employee-binding, restart, and local
endpoint facts before comparing the closed metrics with this file.

The baseline does not prove that a stopped DSH process can cold-resume a live
Session. The fixed SDK still exposes no cold Session resume or Attempt-observe
API. Restart recovery therefore records `runtime_process_lost` and requires an
explicit new Attempt. Likewise, approval decisions remain operator-owned Company
API facts; the DSH control channel does not expose approval control. These are
tested limitations, not substituted runtime features.
Consequently, `runtime_process_lost_retry_not_completed` is the stable recovery
outcome when the exact new Attempt reaches a closed `blocked` or `failed` state
but the pinned DSH cannot cold-resume the stopped Session. The live facts retain
the concrete terminal state, safe failure code, and local request count.
