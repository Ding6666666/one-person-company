# DSH Company Workbench Visual Redesign

**Date:** 2026-08-22

## Goal

Replace the rough, loosely structured Company overlay with a polished workbench that adopts the proven information architecture of the local Multi Agent product while retaining DSH Company's employee-card identity. The result should feel energetic and professional, use vivid color deliberately, and improve hierarchy without changing Company business behavior or API contracts.

## Design Reference and Product Identity

The implementation may study the local `E:\Project\dsh\multi-agent` client for layout, navigation, density, responsive behavior, and state presentation. DSH Company must not import Multi Agent components or styles at runtime. Company owns its implementation and visual tokens.

The shared design language is a compact application header, fixed workbench navigation, structured content pages, purposeful cards, clear states, and responsive mobile navigation. DSH Company differentiates itself through employee avatars, collectible-card depth, company-focused copy, and a more vivid blue–violet–cyan palette.

## Visual System

The Company overlay defines reusable CSS variables for:

- Canvas, surface, subtle surface, border, primary text, and secondary text
- Electric blue, violet, cyan, emerald, orange, magenta, and danger colors
- Control, card, and panel radii
- Compact spacing scale
- Page and section typography
- Card, hover, action, and floating shadows
- Motion durations between 160ms and 220ms

The canvas is a low-saturation blue-grey with faint blue and violet radial glows. Vivid colors appear on navigation selection, primary actions, status accents, card edges, badges, and identity marks rather than filling every surface.

Status colors are stable:

- Running or active work: cyan
- Completed or healthy: emerald
- Waiting, blocked, or approval-needed: orange
- Failed or rejected: magenta-to-red
- Neutral or unavailable: grey

All motion respects `prefers-reduced-motion`. Keyboard focus uses a visible violet-blue outline.

## Application Shell

The full-screen overlay uses two explicit rows: a 64px application header and a remaining minmax content row. This prevents the current header from consuming unused vertical space.

### Header

The header contains:

- A blue–violet–cyan gradient Company mark
- The `DSH Company` product name
- The selected company name when available
- A compact service status indicator
- A quiet close icon button when the overlay controller supports closing

The header remains visually compact and does not scroll with page content.

### Workbench

The desktop workbench has a 248px navigation rail and a flexible content page. The page owns scrolling; the shell and navigation remain stable.

On narrow screens, the desktop rail disappears and a bottom navigation bar exposes the current workspace, Employees, and Work destinations. Content receives safe bottom padding so controls are not covered.

## Company Navigation

The rail begins with a vivid workspace selector card showing the current company name, a compact company mark, and employee count. Activating it expands an accessible workspace list. Creating a workspace is an action at the end of that list rather than a large empty sidebar card.

The primary navigation contains:

- Employee Center, with employee count
- Work Center, with work count

Each destination uses an icon, title, one-line description, and count badge. The selected destination receives a blue-violet gradient, white foreground, and action shadow.

The navigation footer shows a compact Company status summary using existing snapshot data: total employees, known work count, and service/activity state. It does not introduce a backend request.

## Employee Center

### Page Header

The employee page begins with an eyebrow, title, concise description, workspace context, and a vivid gradient Create Employee button.

Below it, compact statistic cards show values that can be computed honestly from current data:

- Total employees
- Active employees
- Number of distinct role types
- Number of distinct configured models

### Empty State

When no employees exist, the page presents a complete empty-state panel rather than plain text. It contains the Custom question-mark avatar, a clear title and explanation, three short capability examples, and a primary Create Employee action. The empty state reuses the existing creation dialog.

### Employee Cards

Created employees appear in a responsive grid. Each card shows:

- Role avatar
- Nickname and work type
- Responsibility summary
- Lifecycle status
- Runtime profile or permission summary
- Model
- Skill and Tool reference counts

The card has a role-sensitive gradient edge and avatar glow. Hover and keyboard focus raise the card and reveal the extended metadata without making essential information hover-only.

Activating a card opens an accessible right-side detail drawer. It presents the full responsibility, role template, model, runtime profile, explicit permissions, Skill references, Tool references, and stable employee identifiers. Closing restores focus to the triggering card.

## Work Center

### Page Header and Statistics

The work page uses the same header and statistic pattern as Employee Center. Existing data provides total, running, waiting/blocked, and completed counts. The Create Work action remains available only when a workspace is selected.

### Work Collection

The current permanently split list/detail area becomes a responsive work collection with clear status accents. Each item shows objective, strategy, status, node progress, and creation context available from the current projection.

Selecting work opens or expands a detail surface without leaving the page. Desktop may use a right-side drawer; narrow screens use the same drawer as a full-width sheet. Existing `WorkDetail` content, governance actions, graph presentation, polling, and cancellation remain authoritative.

## Shared States

Loading states use fixed-size skeleton cards to avoid large layout jumps. Empty states use illustrated panels with one clear action. Error states show only stable, non-sensitive copy and a retry affordance where a retry already exists. Stale data remains visible with a compact warning rather than being replaced by an empty page.

Buttons, cards, selectors, dialogs, and drawers share Company design primitives. Primary actions use the brand gradient. Secondary actions use white surfaces and colored hover borders. Destructive actions remain visually distinct and never use the primary gradient.

## Component Architecture

`CompanySurface` remains responsible for controller state, mutations, dialog state, and page composition. Presentation is separated into focused units:

- `CompanyHeader`: brand, company context, activity status, and close action
- `CompanyNavigation`: workspace selector, page destinations, counts, and status summary
- `CompanyMobileNavigation`: narrow-screen navigation
- `CompanyPageHeader`: shared page title, description, context, and primary action
- `CompanyStats`: reusable, data-driven statistic cards
- `CompanyEmptyState`: illustrated empty-state panel
- Existing `EmployeeDirectory`, `WorkList`, and `WorkDetail`: redesigned around the shared workbench primitives

Company-specific icons are code-native SVG components so they inherit current color, remain crisp, and do not add an external asset dependency. Existing generated employee avatar bitmaps remain the identity source for employee cards and empty states.

## Data and Behavior

No Company API, persistence, or controller contract changes are required. Workspace selection, employee creation, work creation, work polling, governance, cancellation, and dialogs retain their existing behavior.

Statistics derive from the existing `CompanyController` snapshot. Empty-state actions invoke the same dialog callbacks as page-header actions. Responsive presentation does not duplicate business state or create a second navigation model.

The employee creation wizard retains its approved five-step structure and professional prompt editing. Only surrounding dialog chrome and shared design tokens change so it fits the new workbench.

## Accessibility and Responsive Behavior

- Header, navigation, main content, dialogs, drawers, and status regions use appropriate landmarks.
- Current navigation uses `aria-current`; toggle controls expose expanded state.
- Hover-revealed content is also available through keyboard focus and the details drawer.
- Drawer focus is trapped and restored to its trigger when closed.
- Controls retain at least a 40px interaction height.
- Desktop grids collapse cleanly at 760px and below.
- Mobile bottom navigation does not cover content or dialog actions.
- Reduced-motion users receive no decorative transitions or pulsing effects.

## Testing

Automated client coverage must verify:

- The shell renders an explicit header, desktop navigation, and content workbench.
- Selecting a workspace and Employees or Work calls the existing controller paths.
- Counts and statistics are derived from supplied snapshot data.
- Employee and work empty states expose the existing create actions.
- Employee cards show required identity and runtime metadata.
- Employee details open and close through pointer and keyboard interaction.
- Work status values expose stable visual-state attributes.
- Desktop and mobile navigation contain equivalent destinations.
- Existing employee creation, work creation, polling, governance, and error behavior remains passing.

Final verification includes plugin type checking, host and client builds, the complete plugin test suite, and local browser inspection of empty Employee Center, populated employee cards, Work Center, detail drawer, and a narrow viewport.

## Out of Scope

- Backend, OpenAPI, or persistence changes
- New employee or work fields
- A virtual-office or game-map scene
- New Skill or Tool runtime behavior
- Replacing the approved employee creation wizard
- Importing Multi Agent as a dependency
- Uploading or publishing the repository

