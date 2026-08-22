# Employee Role Card Creation Design

**Date:** 2026-08-22

## Goal

Replace the rigid employee form with a guided, card-based experience that helps a user choose and understand an AI employee before configuring it. The first release covers product and software roles, keeps every generated value editable, and prepares real extension points for future Skill and Tool catalogs without pretending those catalogs already exist.

## Scope

The first release includes these role templates:

- Product manager
- Frontend engineer
- Backend engineer
- Full-stack engineer
- Algorithm engineer
- Test engineer
- Custom role

The architecture must allow later role templates such as secretary, operations, copywriting, research, and business analysis to be added as data rather than as new form branches. Those later templates are not shown in this release.

## Creation Flow

Employee creation is a five-step flow:

1. Choose role
2. Complete profile
3. Set permissions
4. Configure capabilities
5. Review and create

The header shows the active step and progress. A sticky footer provides Back and Next actions, while the final step shows a complete employee profile before submission. Going backward preserves all entered values. Failed creation also preserves the draft.

## Role Card Library

Selecting “Create employee” first opens a responsive role-card grid. Each card shows:

- An original avatar
- Role name
- One-sentence purpose
- Default permission badge
- Recommended model
- Typical task tags

Hovering or keyboard-focusing a card raises it and reveals the full responsibility, common tasks, permission summary, and recommended model. Touch and reduced-hover environments expose the same content by tapping the card; no required information is hover-only. Clicking a card selects it and advances to editable profile details.

The interaction may borrow the depth and reveal pattern of a collectible game card, but all visual assets, shapes, colors, and decorations must be original and consistent with DSH Company.

## Avatars

ImageGen will produce seven original transparent-background bitmap avatars in one coherent “3D emoji badge” style:

- Product manager: compass and route nodes
- Frontend engineer: browser window and color palette
- Backend engineer: server and gear
- Full-stack engineer: connected frontend and backend modules
- Algorithm engineer: brain and data network
- Test engineer: magnifier and quality check
- Custom role: a large, prominent question mark

Templates select their default avatar automatically. The custom role starts with the question-mark avatar. The selected avatar is shown on created employee cards, and the profile flow allows it to be changed later without changing the role template.

## Editable Profile

A template is an editable starting point, not a locked persona. It pre-fills:

- Work type
- Suggested nickname
- Responsibility
- Permission level
- Recommended model

Nickname and responsibility inputs include pale, role-specific examples. The user may change every pre-filled value. The custom role contains no fixed content and instead shows clear examples for work type, nickname, and responsibility.

## Permission Selector

Permissions use a five-position horizontal control:

`Observer → Collaborator → Executor → Administrator → Custom`

Clicking or sliding to any position expands its explanation immediately below the control.

- **Observer:** respond, read workspace content, and inspect session history; no writes, terminal execution, or network access.
- **Collaborator:** observer abilities plus work delegation; intended for planning, review, and analysis.
- **Executor:** collaborator abilities plus workspace changes, terminal execution, and authorized network access.
- **Administrator:** executor abilities plus high-impact actions supported by the active runtime; high-risk actions require approval and never bypass workspace or host policy.
- **Custom:** begins with exactly the Executor permission set and allows individual capabilities to be changed.

The custom editor lists all actions known by the capability catalog using human labels and descriptions. Technical identifiers are secondary text. Core entries are:

- Respond to conversations (`conversation.respond`)
- Read workspace (`workspace.read`)
- Read session history (`session.history.read`)
- Delegate work (`work.delegate`)
- Modify workspace (`workspace.write`)
- Run terminal tools (`tool.shell`)
- Access network (`tool.network`)
- Publish externally (`external.publish`)

Each action displays its risk level, resource scope, approval requirement, and runtime support status. An action known to the catalog but unavailable in the active runtime remains visible and disabled with an explanation. Editing any standard preset changes the selector to Custom. Plugin-contributed actions appear through the same catalog rather than through hard-coded form fields.

## Skills and Tools

The capability step has separate Skill and Tool sections.

In this release both display truthful empty states: “No Skill source connected” and “No Tool source connected.” The UI does not show fake examples, accept unverifiable identifiers, or imply that unavailable capabilities are active.

The implementation defines extension contracts for:

- Listing connected capability sources
- Listing importable entries
- Importing an entry
- Selecting and removing employee references
- Resolving reference metadata such as name, source, and version

Role templates and employee drafts support `skill_refs` and `tool_refs`; both arrays are empty until a future source is connected. Tool metadata can declare required permission actions so the UI can detect permission conflicts before creation.

This release does not implement a Skill catalog, Tool catalog, installer, marketplace, or runtime activation.

## Model Selection

Models are displayed as single-select cards sourced from models actually available in the active DSH environment. A model card shows its display name, suitable tasks, expected response speed, and whether the selected role recommends it.

The role recommendation is selected by default when available. If unavailable, the flow selects the system default and explains the fallback. An advanced “Custom model” option accepts a model identifier without making it the primary path.

## Data and Interfaces

Role templates are data-driven records consumed by the client. They contain stable template keys, localized content, avatar references, editable profile defaults, permission presets, model recommendations, and future Skill/Tool references.

Employee create, revision, and projection contracts persist:

- Role template key
- Work type
- Avatar reference
- Responsibility
- Runtime profile
- Model identifier
- Explicit grants
- Skill references
- Tool references

New fields use explicit defaults when reading older employee records. Permission presets map to the existing runtime profiles and grant actions; the saved result remains the actual runtime profile and explicit grant set, not just a decorative UI level.

Skill and Tool source interfaces are separate because instructions and executable capabilities have different metadata and permission needs. Their shared reference shape may be reused where it remains meaningful.

## Validation and Error Handling

- Each step validates only fields needed to continue and focuses the first invalid field.
- The final submission still performs complete schema validation.
- A Tool whose declared actions exceed the selected permissions blocks continuation and names the missing permissions.
- An unavailable recommended model triggers a visible fallback to the system default.
- Missing Skill or Tool sources are normal empty states, not errors.
- API failures keep the draft and provide a retry action.
- Existing dialog focus trapping, Escape handling, keyboard navigation, and localized errors remain supported.

## Testing

Required automated coverage includes:

- All six templates populate the correct editable defaults.
- The custom role starts without fixed profile content and uses the question-mark avatar.
- Hover, focus, and click paths expose equivalent role details.
- Every permission position expands the correct explanation.
- Custom permissions begin with the exact Executor set.
- Editing a preset switches the selector to Custom.
- Skill and Tool empty states are truthful and their provider contracts accept future test providers.
- Model choices come from the active catalog and fallback correctly.
- Step validation, backward navigation, retained drafts, and final submission work.
- New API fields persist and older employee rows receive their defined defaults.
- Existing employee creation and governance behavior remains passing.

## Out of Scope

- Non-product-and-technology role templates
- Skill or Tool marketplace and installation
- Skill or Tool runtime activation
- User-uploaded avatar generation
- Copying visual assets or branding from an existing card game
