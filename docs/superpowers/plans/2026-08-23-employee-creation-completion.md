# Employee Creation Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make employee nicknames optional, close the creation dialog after a valid success, render the new employee immediately, accept the employee response shapes produced by the running local service, and add an explicit dialog close control.

**Architecture:** Keep the backend-required `display_name` populated by deriving it in `EmployeeForm` from nickname or work type. Normalize only the legacy revision fields observed in running Company Service responses at the `ProductApi` boundary, leaving core employee fields strict. Add the close control to the existing `Dialog` primitive so focus management and every dialog's close semantics remain centralized.

**Tech Stack:** React 19, TypeScript, Zod, Vitest, Testing Library, CSS Modules

---

### Task 1: Optional nickname and derived display name

**Files:**
- Modify: `apps/dsh-company-plugin/tests/employee-wizard.client.spec.tsx`
- Modify: `apps/dsh-company-plugin/src/client/EmployeeForm.tsx`

- [ ] **Step 1: Write the failing form tests**

Add tests that select a role, leave nickname blank, complete the wizard, and assert that `onSave` receives `display_name` equal to the selected work type. Add a second assertion that an entered nickname still takes precedence, and assert that the Chinese label communicates “昵称（选填）”.

```tsx
expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
  display_name: '产品经理',
  work_type: '产品经理',
}))
expect(screen.getByLabelText('昵称（选填）')).toHaveValue('')
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pnpm --filter @dsh/company-plugin test -- employee-wizard.client.spec.tsx`

Expected: FAIL because the current identity schema requires a nickname and the label does not mark it optional.

- [ ] **Step 3: Implement the minimal form behavior**

Make `displayName` optional in the identity schema, change the localized label and required-message copy, derive one final name at submit/review time, and keep the input state unchanged.

```ts
displayName: z.string().trim().max(120),
const resolvedDisplayName = parsed.data.displayName || parsed.data.workType
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `pnpm --filter @dsh/company-plugin test -- employee-wizard.client.spec.tsx`

Expected: PASS.

### Task 2: Explicit dialog close control

**Files:**
- Modify: `apps/dsh-company-plugin/tests/company-core.client.spec.tsx`
- Modify: `apps/dsh-company-plugin/src/client/ui/Primitives.tsx`
- Modify: `apps/dsh-company-plugin/src/client/Primitives.module.css`
- Modify: `apps/dsh-company-plugin/src/client/CompanySurface.tsx`

- [ ] **Step 1: Write the failing close-control test**

Open the employee dialog, locate a button named “关闭创建员工”, click it, and assert that the dialog is removed.

```tsx
await user.click(screen.getByRole('button', { name: '关闭创建员工' }))
expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pnpm --filter @dsh/company-plugin test -- company-core.client.spec.tsx`

Expected: FAIL because `Dialog` has no visible close button.

- [ ] **Step 3: Implement the dialog header and close button**

Extend `Dialog` with an optional `closeLabel`, render a title-row button that invokes `onClose`, and pass the localized employee-specific label from `CompanySurface`. Style the control with the existing focus ring and responsive dialog spacing.

```tsx
<header className={styles.dialogHeader}>
  <h2 id={titleId}>{title}</h2>
  <button type="button" className={styles.dialogClose} aria-label={closeLabel} onClick={onClose}>×</button>
</header>
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `pnpm --filter @dsh/company-plugin test -- company-core.client.spec.tsx`

Expected: PASS.

### Task 3: Normalize observed employee response versions

**Files:**
- Modify: `apps/dsh-company-plugin/tests/company-core.client.spec.tsx`
- Modify: `apps/dsh-company-plugin/src/client/api.ts`

- [ ] **Step 1: Write failing API-boundary tests**

Exercise `ProductApi.createEmployee` with both observed legacy revision shapes: one missing only `system_prompt`, and one also missing the role profile and capability reference fields. Assert the returned employee contains the documented defaults. Keep a test proving that a missing core field such as `binding` still raises `invalid_company_response`.

```ts
expect(result.revision).toMatchObject({
  system_prompt: '',
  role_template_key: 'custom',
  work_type: '自定义工作',
  avatar_key: 'custom',
  skill_refs: [],
  tool_refs: [],
})
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pnpm --filter @dsh/company-plugin test -- company-core.client.spec.tsx`

Expected: FAIL with `invalid_company_response` for the observed legacy responses.

- [ ] **Step 3: Implement narrow schema defaults**

Add Zod defaults only to the six revision fields absent from the observed responses; do not make employee identity, status, binding, grants, or revision identity optional.

```ts
system_prompt: z.string().default(''),
role_template_key: z.string().default('custom'),
work_type: z.string().default('自定义工作'),
avatar_key: z.string().default('custom'),
skill_refs: z.array(z.string()).default([]),
tool_refs: z.array(z.string()).default([]),
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `pnpm --filter @dsh/company-plugin test -- company-core.client.spec.tsx`

Expected: PASS.

### Task 4: Successful creation lifecycle

**Files:**
- Modify: `apps/dsh-company-plugin/tests/company-core.client.spec.tsx`
- Modify if required by the failing test: `apps/dsh-company-plugin/src/client/CompanySurface.tsx`

- [ ] **Step 1: Strengthen the creation integration test**

Use an observed compatible response, submit the employee form, and assert all three outcomes together: the POST occurred, the dialog closed, and the employee card heading became visible without a reload. Add the complementary failed-response assertion that the dialog stays open.

```tsx
expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
expect(await screen.findByRole('heading', { name: '产品经理' })).toBeVisible()
expect(screen.queryByText('invalid_company_response')).not.toBeInTheDocument()
```

- [ ] **Step 2: Run the focused test and verify its result**

Run: `pnpm --filter @dsh/company-plugin test -- company-core.client.spec.tsx`

Expected: PASS after Tasks 1–3. If it fails, change only the creation lifecycle condition demonstrated by the failure.

- [ ] **Step 3: Apply a minimal lifecycle correction only if RED**

Preserve the current success guard and close only when the controller returns an employee.

```ts
const created = await controller.createEmployee(input)
if (created !== undefined) closeEmployeeDialog()
```

- [ ] **Step 4: Re-run the focused test**

Run: `pnpm --filter @dsh/company-plugin test -- company-core.client.spec.tsx`

Expected: PASS.

### Task 5: Necessary verification

**Files:**
- No production files expected

- [ ] **Step 1: Run the affected client tests**

Run: `pnpm --filter @dsh/company-plugin test -- employee-wizard.client.spec.tsx company-core.client.spec.tsx`

Expected: PASS.

- [ ] **Step 2: Run plugin type checking**

Run: `pnpm --filter @dsh/company-plugin typecheck`

Expected: PASS.

- [ ] **Step 3: Run the plugin client build**

Run: `pnpm --filter @dsh/company-plugin build:client`

Expected: PASS.

- [ ] **Step 4: Perform one browser smoke check**

Open the local Company page, verify the employee dialog has the explicit close control, create an employee with an empty nickname, and confirm the dialog closes and the card renders. Record only pass/fail and non-sensitive errors.

