import { type FormEvent, useMemo, useState } from 'react'
import { z } from 'zod'

import type { EmployeeCreate } from './api.js'
import { employeeAvatars } from './employee-creation/avatars.js'
import { permissionActions, permissionPresets } from './employee-creation/permissions.js'
import { roleTemplates } from './employee-creation/roleTemplates.js'
import type { CoreAction, PermissionPresetKey, RoleTemplate, RoleTemplateKey } from './employee-creation/types.js'
import type { Translate } from './locales.js'
import styles from './EmployeeForm.module.css'
import { Button, Field } from './ui/Primitives.js'

const identitySchema = z.object({
  workType: z.string().trim().min(1).max(120),
  displayName: z.string().trim().max(120),
  responsibility: z.string().trim().min(1).max(4000),
  systemPrompt: z.string().trim().min(1).max(12000),
})

const stepLabels = {
  zh: ['选择角色', '完善档案', '设置权限', '配置能力', '确认创建'],
  en: ['Choose role', 'Profile', 'Permissions', 'Capabilities', 'Review'],
} as const

const copy = {
  zh: {
    next: '下一步', back: '上一步', workType: '工作类型', nickname: '昵称（选填）', roleIntro: '选择一个角色模板',
    roleHint: '点击卡片可查看完整职责；模板内容之后仍可修改。', permissionTitle: '这位员工可以做什么？',
    permissionHint: '选择一个清晰的权限档位。自定义默认与执行者相同，可逐项调整。', skills: 'Skill', tools: 'Tool',
    noSkills: '暂未连接 Skill 来源', noTools: '暂未连接 Tool 来源', importReady: '导入接口已就绪，后续接入来源后可在这里选择。',
    modelTitle: '工作模型', modelHint: '默认采用当前运行时推荐模型，也可以输入自定义模型标识。', customModel: '使用自定义模型',
    review: '确认员工档案', permission: '权限', capability: '能力', none: '暂未配置', create: '创建员工',
    customPermission: '逐项选择权限', unsupported: '当前运行时暂不支持', required: '请完整填写工作类型和职责。',
    advanced: '高级设置', systemPrompt: 'System Prompt', systemPromptHint: '定义这位员工的工作方法、边界和交付标准。模板已生成专业版本，你可以按需修改。',
  },
  en: {
    next: 'Next', back: 'Back', workType: 'Work type', nickname: 'Nickname (optional)', roleIntro: 'Choose a role template',
    roleHint: 'Select a card to see the full responsibility. You can edit every default later.', permissionTitle: 'What can this employee do?',
    permissionHint: 'Choose a clear permission level. Custom starts with Executor and can be adjusted action by action.', skills: 'Skill', tools: 'Tool',
    noSkills: 'No Skill source connected', noTools: 'No Tool source connected', importReady: 'The import interface is ready for future sources.',
    modelTitle: 'Work model', modelHint: 'Uses the runtime recommendation by default; a custom model identifier is also available.', customModel: 'Use a custom model',
    review: 'Review employee profile', permission: 'Permission', capability: 'Capabilities', none: 'None configured', create: 'Create employee',
    customPermission: 'Choose permissions individually', unsupported: 'Not supported by the current runtime', required: 'Complete work type and responsibility.',
    advanced: 'Advanced settings', systemPrompt: 'System Prompt', systemPromptHint: 'Defines how this employee works, its boundaries, and delivery standard. A professional template is provided and remains editable.',
  },
} as const

const presetOrder: readonly PermissionPresetKey[] = ['observer', 'collaborator', 'executor', 'administrator', 'custom']
const localized = (value: { readonly zh: string; readonly en: string }, language: 'zh' | 'en'): string => value[language]

export function EmployeeForm({ pending, onCancel, onSave, t, modelOptions = [] }: {
  readonly pending: boolean
  readonly onCancel: () => void
  readonly onSave: (input: EmployeeCreate) => Promise<void>
  readonly t: Translate
  readonly modelOptions?: readonly string[]
}) {
  const language = t('cancel') === 'Cancel' ? 'en' : 'zh'
  const c = copy[language]
  const [step, setStep] = useState(0)
  const [templateKey, setTemplateKey] = useState<RoleTemplateKey>('custom')
  const [expandedTemplate, setExpandedTemplate] = useState<RoleTemplateKey>()
  const [workType, setWorkType] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [responsibility, setResponsibility] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [permissionKey, setPermissionKey] = useState<PermissionPresetKey>('executor')
  const [expandedPermission, setExpandedPermission] = useState<PermissionPresetKey>('executor')
  const [customActions, setCustomActions] = useState<readonly CoreAction[]>(permissionPresets.custom.actions)
  const [model, setModel] = useState('deepseek-v4-flash')
  const [customModel, setCustomModel] = useState(false)
  const [error, setError] = useState<string>()

  const template = roleTemplates.find(item => item.key === templateKey) ?? roleTemplates.at(-1)!
  const selectedActions = permissionKey === 'custom' ? customActions : permissionPresets[permissionKey].actions
  const resolvedDisplayName = displayName.trim() || workType.trim()
  const availableModels = useMemo(() => [...new Set([template.recommendedModel, ...modelOptions])], [modelOptions, template.recommendedModel])

  const chooseTemplate = (next: RoleTemplate): void => {
    setTemplateKey(next.key); setExpandedTemplate(next.key)
    setWorkType(localized(next.workType, language)); setResponsibility(localized(next.responsibility, language))
    setDisplayName(''); setSystemPrompt(localized(next.systemPrompt, language)); setAdvancedOpen(false)
    setPermissionKey(next.permissionPreset); setExpandedPermission(next.permissionPreset)
    setCustomActions(permissionPresets.custom.actions); setModel(next.recommendedModel); setError(undefined)
  }

  const goNext = (): void => {
    if (step === 1 && !identitySchema.safeParse({ workType, displayName, responsibility, systemPrompt }).success) {
      setError(c.required); return
    }
    setError(undefined); setStep(current => Math.min(4, current + 1))
  }

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault()
    if (step !== 4) { goNext(); return }
    const parsed = identitySchema.safeParse({ workType, displayName, responsibility, systemPrompt })
    if (!parsed.success || model.trim().length === 0) { setError(c.required); return }
    const grants = selectedActions.map(action => permissionActions.find(item => item.action === action)!).map(item => ({
      action: item.action, level: item.level, resource_kind: 'workspace', resource_values: ['workspace'], requires_approval: item.requiresApproval,
    }))
    await onSave({
      display_name: parsed.data.displayName || parsed.data.workType, role_template_key: template.key, work_type: parsed.data.workType,
      avatar_key: template.avatarKey, responsibility: parsed.data.responsibility,
      system_prompt: parsed.data.systemPrompt,
      runtime_profile: selectedActions.includes('workspace.write') ? 'workspace_write' : 'workspace_read',
      model: model.trim(), grants, skill_refs: [...template.skillRefs], tool_refs: [...template.toolRefs],
    })
  }

  return <form className={styles.form} onSubmit={event => { void submit(event) }} noValidate>
    <ol className={styles.steps} aria-label={language === 'zh' ? '创建进度' : 'Creation progress'}>
      {stepLabels[language].map((label, index) => <li key={label} aria-current={index === step ? 'step' : undefined} data-complete={index < step}>{index + 1}<span>{label}</span></li>)}
    </ol>

    {step === 0 && <section className={styles.stepPanel}>
      <header className={styles.intro}><div><span>01</span><h3>{c.roleIntro}</h3></div><p>{c.roleHint}</p></header>
      <div className={styles.roleGrid}>{roleTemplates.map(item => {
        const selected = item.key === templateKey && expandedTemplate === item.key
        return <button key={item.key} type="button" className={styles.roleCard} aria-pressed={selected} onClick={() => chooseTemplate(item)}>
          <span className={styles.cardGlow} /><img src={employeeAvatars[item.avatarKey]} alt="" />
          <span className={styles.roleName}>{localized(item.name, language)}</span>
          <span className={styles.roleSummary}>{localized(item.summary, language)}</span>
          <span className={styles.tags}>{item.taskTags.map(tag => <small key={tag.en}>{localized(tag, language)}</small>)}</span>
          {selected && <span className={styles.expanded}><strong>{localized(item.workType, language) || c.workType}</strong>{localized(item.responsibility, language) || localized(item.summary, language)}</span>}
        </button>
      })}</div>
    </section>}

    {step === 1 && <section className={styles.stepPanel}>
      <div className={styles.profileHero}><img src={employeeAvatars[template.avatarKey]} alt="" /><div><span>{localized(template.name, language)}</span><strong>{localized(template.summary, language)}</strong></div></div>
      <div className={styles.fields}>
        <Field label={c.workType}><input maxLength={120} value={workType} placeholder={language === 'zh' ? '例如：产品管理、客户运营' : 'For example: Product operations'} onChange={event => setWorkType(event.target.value)} /></Field>
        <Field label={c.nickname}><input maxLength={120} value={displayName} placeholder={localized(template.nicknameExample, language)} onChange={event => setDisplayName(event.target.value)} /></Field>
        <Field label={t('responsibility')}><textarea maxLength={4000} value={responsibility} placeholder={language === 'zh' ? '例如：梳理需求、确定优先级，并推动方案按时交付。' : 'For example: Clarify needs, prioritize, and drive delivery.'} onChange={event => setResponsibility(event.target.value)} /></Field>
      </div>
      <section className={styles.advancedPanel}>
        <button type="button" aria-label={c.advanced} aria-expanded={advancedOpen} onClick={() => setAdvancedOpen(current => !current)}><span>{c.advanced}</span><small aria-hidden="true">{advancedOpen ? '−' : '+'}</small></button>
        {advancedOpen && <div className={styles.promptEditor}><p>{c.systemPromptHint}</p><Field label={c.systemPrompt}><textarea maxLength={12000} value={systemPrompt} onChange={event => setSystemPrompt(event.target.value)} /></Field></div>}
      </section>
    </section>}

    {step === 2 && <section className={styles.stepPanel}>
      <header className={styles.intro}><div><span>03</span><h3>{c.permissionTitle}</h3></div><p>{c.permissionHint}</p></header>
      <div className={styles.permissionTrack}>{presetOrder.map(key => <button type="button" key={key} aria-pressed={permissionKey === key} onClick={() => { setPermissionKey(key); setExpandedPermission(key) }}><span>{localized(permissionPresets[key].label, language)}</span><small>{permissionPresets[key].actions.length}</small></button>)}</div>
      <article className={styles.permissionDetail}>
        <h4>{localized(permissionPresets[expandedPermission].label, language)}</h4><p>{localized(permissionPresets[expandedPermission].description, language)}</p>
        {expandedPermission === 'custom' && <strong>{c.customPermission}</strong>}
        <div className={styles.actionGrid}>{permissionActions.map(item => {
          const checked = selectedActions.includes(item.action)
          return <label key={item.action} data-disabled={!item.runtimeSupported} data-selected={checked && item.runtimeSupported}><input type="checkbox" disabled={permissionKey !== 'custom' || !item.runtimeSupported} checked={checked} onChange={event => setCustomActions(current => event.target.checked ? [...current, item.action] : current.filter(action => action !== item.action))} /><span><strong>{localized(item.label, language)}</strong><small>{localized(item.description, language)}{!item.runtimeSupported ? ` · ${c.unsupported}` : ''}</small></span></label>
        })}</div>
      </article>
    </section>}

    {step === 3 && <section className={styles.stepPanel}>
      <div className={styles.capabilityGrid}>
        <article><span className={styles.capabilityIcon}>S</span><div><h3>{c.skills}</h3><strong>{c.noSkills}</strong><p>{c.importReady}</p></div></article>
        <article><span className={styles.capabilityIcon}>T</span><div><h3>{c.tools}</h3><strong>{c.noTools}</strong><p>{c.importReady}</p></div></article>
      </div>
      <article className={styles.modelPanel}><h3>{c.modelTitle}</h3><p>{c.modelHint}</p>
        {!customModel && <Field label={t('model')}><select value={model} onChange={event => setModel(event.target.value)}>{availableModels.map(item => <option key={item}>{item}</option>)}</select></Field>}
        {customModel && <Field label={t('model')}><input maxLength={200} value={model} onChange={event => setModel(event.target.value)} /></Field>}
        <label className={styles.customModel}><input type="checkbox" checked={customModel} onChange={event => setCustomModel(event.target.checked)} /> {c.customModel}</label>
      </article>
    </section>}

    {step === 4 && <section className={styles.stepPanel}>
      <h3 className={styles.reviewTitle}>{c.review}</h3>
      <article className={styles.reviewCard}><img src={employeeAvatars[template.avatarKey]} alt="" /><div><span>{localized(template.name, language)} · {workType}</span><h3>{resolvedDisplayName}</h3><p>{responsibility}</p></div></article>
      <dl className={styles.reviewFacts}><div><dt>{c.permission}</dt><dd>{localized(permissionPresets[permissionKey].label, language)} · {selectedActions.length}</dd></div><div><dt>{t('model')}</dt><dd>{model}</dd></div><div><dt>{c.capability}</dt><dd>{template.skillRefs.length + template.toolRefs.length || c.none}</dd></div></dl>
    </section>}

    {error !== undefined && <p className={styles.error} role="alert">{error}</p>}
    <footer className={styles.actions}><Button type="button" onClick={step === 0 ? onCancel : () => setStep(current => current - 1)}>{step === 0 ? t('cancel') : c.back}</Button><Button type="submit" className={styles.primary} disabled={pending}>{step === 4 ? c.create : c.next}</Button></footer>
  </form>
}
