# Company Group Chat and API Credentials Design

Date: 2026-08-23
Status: Approved in conversation; awaiting written-spec review

## Objective

Add two connected capabilities to DSH Company:

1. A Company-owned entry point for configuring the DeepSeek API key through DSH's existing credential service.
2. A first-class company group chat where the user can talk normally, direct employees with `@` mentions, and continue conversations attached to formal Work items.

The group chat is independent of Work Center. Lightweight chat instructions do not create hidden Work records. Formal Work remains the source of truth for tracked execution and appears in chat through linked task cards and task discussion threads.

## Product Decisions

### Lightweight instructions versus formal Work

- A normal `@employee` message creates a lightweight instruction execution inside chat.
- Lightweight instructions do not create Work records and do not appear in Work Center.
- A chat instruction can be converted into formal Work through an explicit "Convert to work" action. The action pre-fills the Work composer, but the user must still confirm strategy, acceptance criteria, and responsible employees.
- Work created in Work Center remains formal, tracked Work.

### Conversation organization

- Every company workspace has one implicit company group conversation; users do not create or name it.
- Formal Work appears in that group as a linked task-card message.
- Each Work task card opens one discussion thread associated with its `work_id`.
- The company group is the default Company view and can be opened without passing through Work Center.

### Credential scope

- The first version manages only `DEEPSEEK_API_KEY`.
- It uses the existing DSH credentials API and host credential provider.
- The stored secret is write-only from the browser's perspective. The UI never reads or displays the credential value.
- Base URL, multiple providers, and provider switching are outside this version.

## Information Architecture

The Company surface uses four stable destinations:

- **Company Chat**: default landing view and everyday team interaction.
- **Work Center**: formal tracked tasks, strategies, approvals, and results.
- **Employees**: employee directory and employee creation.
- **Settings and API**: DeepSeek credential status and write-only configuration.

The left navigation exposes Company Chat, Work Center, and Employees as primary destinations. Settings and API remains persistently available at the bottom of the navigation. The chat header shows a compact API configuration status that opens the same settings panel. A right rail shows current company members and active Work discussions.

## Credential Configuration

### UI behavior

The API panel shows:

- configured or unconfigured status;
- the credential source when available;
- whether the current source is writable;
- an empty input for replacing the key;
- save and clear actions when writable.

The input is blank every time the panel opens. Saving a new value clears the input immediately after success. Clearing a configured credential requires one confirmation. If the credential is supplied by a read-only environment source, the panel explains that the environment manages it and disables replacement and removal.

If an employee execution is requested while the credential is unavailable, the corresponding execution state explains that a DeepSeek API key is required and includes a direct link to the API panel. Ordinary chat reading and message persistence remain available.

### Technical integration

The Company client receives the existing DSH connection credentials API through its slot injection. It calls:

- `credentials.describe` for `DEEPSEEK_API_KEY` to obtain value-free status;
- `credentials.set` to store a replacement value;
- `credentials.unset` to clear a writable stored value.

No Company database table, settings YAML entry, log entry, or browser-readable response stores the secret. The existing Company host already resolves `credentialRef('DEEPSEEK_API_KEY')` and reacts to `credentials/updated`; that lifecycle remains responsible for reloading Company Service after a successful change.

## Conversation Domain

### Persistent records

The Company service adds focused records for:

- a workspace's implicit company conversation;
- messages;
- optional Work discussion threads;
- structured employee mentions;
- per-mentioned-employee lightweight execution state.

A message has an author kind (`user`, `employee`, or `system`), body, creation time, and optional reply relationship. A task-card message additionally carries a `work_id`. A task-thread message carries the same `work_id` as its thread. Mention targets use stable employee IDs rather than parsed display names.

Lightweight execution state belongs to the originating message and one mentioned employee. Its states are `queued`, `running`, `completed`, and `failed`, with a non-sensitive user-facing failure reason when applicable. Employee replies link to both the originating message and employee execution.

### Source-of-truth boundaries

- Chat owns messages, lightweight executions, and discussion-thread content.
- Work Center owns formal Work strategy, graph, assignments, approvals, lifecycle status, and results.
- A chat task card references Work and reads its current status; it does not maintain a second Work status.
- Work runtime events add selected human-readable system messages to the linked discussion thread. Raw runtime logs are not copied into chat.

## Mention and Execution Flow

1. The composer resolves selected autocomplete entries into stable employee IDs and sends the text plus structured mention targets.
2. The backend validates the workspace, active employees, and `conversation.respond` capability.
3. It persists the user message first.
4. A message without mentions ends as an ordinary persisted group message.
5. A message with mentions creates one independent lightweight execution per mentioned employee and returns immediately with queued states.
6. The chat application service submits each lightweight execution through a dedicated chat submission contract in the existing DSH Gateway boundary.
7. A submission uses the employee's current revision, Session, model, system prompt, permissions, Skills, and Tools. It receives the originating message and a bounded amount of relevant conversation context. A task discussion additionally provides the formal Work context identified by `work_id`.
8. Each employee reply and final execution state is persisted independently. One failure does not block replies from other mentioned employees.
9. The client refreshes messages and execution states through the existing Company API polling pattern. WebSocket transport is outside this version.

Chat submission is a distinct gateway contract. It must not create a synthetic `AttemptId` or disguise chat as a hidden formal Work attempt.

## Work Center Integration

After formal Work creation succeeds, the application writes exactly one linked task-card message to the workspace's company conversation. Creation uses a stable Work-to-message relationship so retries cannot create duplicate task cards.

The task card displays title or objective, strategy, responsible employees, and live status from Work Center. Opening the card enters its discussion thread. Messages and `@` instructions in that thread carry `work_id`, so employee submissions receive the relevant Work context without creating additional Work records.

The discussion thread receives selected lifecycle messages for meaningful user-facing changes:

- execution started;
- employee or approval input required;
- completion;
- failure.

The existing Work detail remains the authoritative view for graph nodes, attempts, approvals, and full results.

## Client Interaction Design

### Chat composer

- Typing `@` opens an employee autocomplete popover.
- Candidates show avatar, nickname when present, role, and a short responsibility label.
- Search matches nickname and role; employees without a nickname remain selectable by role.
- Keyboard navigation, Enter selection, Escape dismissal, and pointer selection are supported.
- Selected mentions are rendered distinctly but serialize to stable employee IDs.
- A single message may mention multiple employees.

### Message states

The originating user message displays a compact state per mentioned employee. Employee replies remain grouped with that message while preserving normal chronological ordering. Status and failures are localized to the affected employee.

Task cards use a visually distinct treatment from ordinary messages and expose "Open discussion". A lightweight instruction reply exposes "Convert to work" without forcing that flow.

### Responsive behavior

On wide screens, navigation, conversation, and member/activity rail can appear together. On narrow screens, the right rail becomes an on-demand panel and the composer remains fixed within the Company surface without horizontal overflow.

## Error Handling

- Missing API credential: preserve the message, mark only requested executions as failed, explain the required configuration, and link to the API panel.
- Inactive or deleted employee: reject that target with an employee-specific reason while processing other valid targets.
- Missing `conversation.respond`: show a permission-specific failure for that employee.
- Unavailable Session or gateway failure: persist a non-sensitive failure reason and allow the user to retry that employee execution.
- Credential save failure: keep the newly typed value only in the input for retry and never place it in logs or error details.
- Work creation retry: reuse the stable Work-to-message relationship and do not create another task card.
- Partial multi-mention failure: completed employee replies remain visible and are never rolled back because another employee failed.

## API and Component Boundaries

The implementation should keep these units independently understandable:

- **Credential panel**: value-free status and set/unset actions; depends only on the DSH credentials API.
- **Chat composer**: text editing, mention selection, and structured message submission; depends on employee summaries and chat client methods.
- **Conversation application service**: message persistence, mention validation, execution creation, and task-card linking.
- **Chat gateway submission**: adapts lightweight employee instructions to the existing employee runtime without creating Work attempts.
- **Work-chat projector**: translates selected formal Work lifecycle changes into linked task-thread system messages.
- **Conversation read model**: returns chronological messages, employee execution states, reply relationships, and current task-card views.

The Company client never calls a model provider directly. All employee execution continues through the Company service and gateway boundaries.

## Verification

### Credential behavior

- unconfigured, configured, and read-only environment-source states;
- successful set and unset;
- saved values never appear in describe responses, rendered UI, logs, or persisted Company data;
- credential update triggers the existing service reload path.

### Conversation behavior

- ordinary persisted message without a mention;
- one and multiple structured employee mentions;
- nickname and role search, including employees without nicknames;
- independent queued, running, completed, and failed states;
- message and reply history survives refresh;
- inactive employee, missing permission, missing credential, and unavailable Session failures remain employee-specific;
- retry targets only the selected failed execution.

### Work integration

- formal Work creation produces exactly one task card;
- task card opens the correct `work_id` discussion;
- task-thread messages provide Work context to mentioned employees;
- selected lifecycle changes appear once in the thread;
- Work status displayed in chat matches the Work source of truth;
- converting a lightweight instruction pre-fills but does not automatically submit formal Work.

### UI and regression

- Company Chat opens independently and is the default Company destination;
- mouse and keyboard mention selection work;
- desktop and narrow viewport layouts avoid horizontal overflow;
- employee creation, employee permissions, all four Work strategies, approvals, and formal Work execution continue to behave as before.

## Out of Scope

- multiple API providers, Base URL configuration, and model-provider switching;
- user-created channels, direct messages, and multiple company group rooms;
- WebSocket or server-sent event transport;
- file attachments, voice messages, reactions, and message editing;
- automatically creating formal Work for every `@` instruction;
- exposing raw runtime logs in chat.
