import type { RoleTemplate } from './types.js'
import { roleSystemPrompts } from './systemPrompts.js'

const text = (zh: string, en: string) => ({ zh, en }) as const
const emptyRefs: readonly string[] = []

export const roleTemplates: readonly RoleTemplate[] = [
  {
    key: 'product-manager', avatarKey: 'product-manager', name: text('产品经理', 'Product manager'),
    summary: text('把用户需求转化为清晰、可执行的产品方案', 'Turn user needs into clear product plans'),
    workType: text('产品管理', 'Product management'), nicknameExample: text('例如：小策', 'For example: Scout'),
    responsibility: text('梳理需求、定义优先级、撰写产品方案，并协调交付与验收。', 'Clarify requirements, prioritize, write product plans, and coordinate delivery.'),
    systemPrompt: roleSystemPrompts['product-manager'],
    taskTags: [text('需求分析', 'Discovery'), text('产品规划', 'Planning'), text('验收', 'Acceptance')],
    permissionPreset: 'collaborator', recommendedModel: 'deepseek-v4-flash', skillRefs: emptyRefs, toolRefs: emptyRefs,
  },
  {
    key: 'frontend-engineer', avatarKey: 'frontend-engineer', name: text('前端工程师', 'Frontend engineer'),
    summary: text('实现清晰、可靠且可访问的产品界面', 'Build clear, reliable, accessible interfaces'),
    workType: text('前端开发', 'Frontend development'), nicknameExample: text('例如：小前', 'For example: Pixel'),
    responsibility: text('实现交互界面、维护前端状态与样式，并验证可访问性和浏览器体验。', 'Build interactions, maintain client state and styling, and verify accessibility.'),
    systemPrompt: roleSystemPrompts['frontend-engineer'],
    taskTags: [text('界面实现', 'UI'), text('交互体验', 'UX'), text('可访问性', 'Accessibility')],
    permissionPreset: 'executor', recommendedModel: 'deepseek-v4-flash', skillRefs: emptyRefs, toolRefs: emptyRefs,
  },
  {
    key: 'backend-engineer', avatarKey: 'backend-engineer', name: text('后端工程师', 'Backend engineer'),
    summary: text('构建稳定的服务、数据与接口', 'Build reliable services, data, and APIs'),
    workType: text('后端开发', 'Backend development'), nicknameExample: text('例如：小端', 'For example: Forge'),
    responsibility: text('设计服务接口和数据模型，完成业务逻辑，并保障可测试性与运行可靠性。', 'Design APIs and data models, implement logic, and protect reliability.'),
    systemPrompt: roleSystemPrompts['backend-engineer'],
    taskTags: [text('接口', 'APIs'), text('数据', 'Data'), text('可靠性', 'Reliability')],
    permissionPreset: 'executor', recommendedModel: 'deepseek-v4-flash', skillRefs: emptyRefs, toolRefs: emptyRefs,
  },
  {
    key: 'fullstack-engineer', avatarKey: 'fullstack-engineer', name: text('全栈工程师', 'Full-stack engineer'),
    summary: text('贯通界面、服务与数据的完整交付', 'Deliver across interface, service, and data'),
    workType: text('全栈开发', 'Full-stack development'), nicknameExample: text('例如：小全', 'For example: Atlas'),
    responsibility: text('完成端到端功能开发，协调前后端边界，并验证完整用户流程。', 'Deliver end-to-end features and verify complete user journeys.'),
    systemPrompt: roleSystemPrompts['fullstack-engineer'],
    taskTags: [text('端到端', 'End-to-end'), text('集成', 'Integration'), text('交付', 'Delivery')],
    permissionPreset: 'executor', recommendedModel: 'deepseek-v4-flash', skillRefs: emptyRefs, toolRefs: emptyRefs,
  },
  {
    key: 'algorithm-engineer', avatarKey: 'algorithm-engineer', name: text('算法工程师', 'Algorithm engineer'),
    summary: text('设计、验证并优化模型与算法方案', 'Design, validate, and optimize algorithms'),
    workType: text('算法研发', 'Algorithm development'), nicknameExample: text('例如：小算', 'For example: Vector'),
    responsibility: text('分析数据和目标，设计算法实验，评估结果并沉淀可复现方案。', 'Analyze data, design experiments, evaluate results, and keep work reproducible.'),
    systemPrompt: roleSystemPrompts['algorithm-engineer'],
    taskTags: [text('实验', 'Experiments'), text('评估', 'Evaluation'), text('优化', 'Optimization')],
    permissionPreset: 'executor', recommendedModel: 'deepseek-v4-flash', skillRefs: emptyRefs, toolRefs: emptyRefs,
  },
  {
    key: 'test-engineer', avatarKey: 'test-engineer', name: text('测试工程师', 'Test engineer'),
    summary: text('发现风险并用证据守住产品质量', 'Find risks and protect quality with evidence'),
    workType: text('质量保障', 'Quality assurance'), nicknameExample: text('例如：小测', 'For example: Lens'),
    responsibility: text('设计测试场景、验证关键流程、记录缺陷，并给出清晰的质量结论。', 'Design scenarios, verify critical flows, record defects, and report quality.'),
    systemPrompt: roleSystemPrompts['test-engineer'],
    taskTags: [text('测试设计', 'Test design'), text('缺陷分析', 'Defects'), text('质量报告', 'Reporting')],
    permissionPreset: 'collaborator', recommendedModel: 'deepseek-v4-flash', skillRefs: emptyRefs, toolRefs: emptyRefs,
  },
  {
    key: 'custom', avatarKey: 'custom', name: text('自定义角色', 'Custom role'),
    summary: text('从空白开始定义一位专属员工', 'Define a dedicated employee from scratch'),
    workType: text('', ''), nicknameExample: text('例如：小智', 'For example: Nova'),
    responsibility: text('', ''), taskTags: [], permissionPreset: 'executor',
    systemPrompt: roleSystemPrompts.custom,
    recommendedModel: 'deepseek-v4-flash', skillRefs: emptyRefs, toolRefs: emptyRefs,
  },
]
