# Software plugin adaptation boundary

The former `multi-agent` software assets stay in their own project. This guide
describes how a future software business plugin can integrate with DSH Company;
it does not copy those assets, migrate their database, or move their runtime
into Company Core.

## Ownership map

| Existing software concern | Company integration |
| --- | --- |
| Git, worktree, command and software runtime tools | Remain implemented and owned by the software plugin. Company Core does not acquire them. |
| Software roles | Become recommended Employee revisions created through the public Employee API; they are not Core enums. |
| Task, Delivery and Integration records | Remain plugin-owned objects linked to public Company `Work` and `ArtifactReference` identifiers. They do not become Core tables. |
| Multi-step software flow | Becomes a declarative business-plugin template instantiated through the public template API. Work, graph validation, approvals and execution remain Core-owned. |
| Progress and approval integration | Uses public work, event and approval endpoints. The plugin never opens or writes the Company database. |

The software plugin may register only actions prefixed by its plugin ID and
declarative templates made of nodes, edges, Employee slots and acceptance
criteria. It cannot replace Core actions or provide executable Python,
JavaScript, SQL, prompt overrides, callback URLs, or package paths in a
manifest.

Registered namespaced actions extend Company's persisted policy catalog. A
template node may declare required actions plus resource kinds and values, while
the action declaration lists the existing Company runtime profiles allowed to
carry it. These declarations are restored from the registry after restart and
are evaluated by the same workspace/Employee/node/runtime intersection, graph
validation, and approval flow as Core actions. They do not install executable
backend code, create a DSH tool, or grant a plugin direct access to Core storage,
DSH sessions, or the Host.

There is deliberately no old-database migration and no compatibility layer.
Existing software records remain where they are; any association is created as
a new plugin-owned reference to public Company IDs. CrewAI flows and types are
not imported into Company Core. Runtime and Memory continue to be DSH-owned,
and the plugin uses the same public Company work/approval boundary as every
other client.
