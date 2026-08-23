import { useSyncExternalStore } from 'react'

import {
  ApiError,
  type ChatMessageProjection,
  type CompanyEvent,
  type DirectWorkCreate,
  type Employee,
  type EmployeeCreate,
  ProductApi,
  type StrategyWorkCreate,
  type WorkProjection,
  type Workspace,
} from './api.js'

export interface CompanySnapshot {
  readonly phase: 'loading' | 'ready' | 'error'
  readonly pending: boolean
  readonly error: string | undefined
  readonly workspaces: readonly Workspace[]
  readonly selectedWorkspaceId: string | undefined
  readonly employees: readonly Employee[]
  readonly works: readonly WorkProjection[]
  readonly selectedWorkId: string | undefined
  readonly selectedWork: WorkProjection | undefined
  readonly events: readonly CompanyEvent[]
  readonly messages: readonly ChatMessageProjection[]
  readonly discussionWorkId: string | undefined
}

const initialSnapshot: CompanySnapshot = {
  phase: 'loading',
  pending: false,
  error: undefined,
  workspaces: [],
  selectedWorkspaceId: undefined,
  employees: [],
  works: [],
  selectedWorkId: undefined,
  selectedWork: undefined,
  events: [],
  messages: [],
  discussionWorkId: undefined,
}

export class CompanyController {
  private current = initialSnapshot
  private readonly listeners = new Set<() => void>()
  private selectionGeneration = 0
  private workRefreshGeneration = 0
  private workListGeneration = 0
  private chatGeneration = 0

  constructor(private readonly api: ProductApi) {}

  snapshot = (): CompanySnapshot => this.current
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  async load(initialWorkspaceId?: string): Promise<void> {
    this.publish({ ...this.current, phase: 'loading', error: undefined })
    try {
      const workspaces = await this.api.listWorkspaces()
      this.publish({ ...this.current, phase: 'ready', workspaces, error: undefined })
      if (initialWorkspaceId !== undefined && workspaces.some(workspace => workspace.id === initialWorkspaceId)) {
        await this.selectWorkspace(initialWorkspaceId)
      }
    } catch (error) {
      this.fail(error)
    }
  }

  async createWorkspace(name: string): Promise<Workspace | undefined> {
    this.publish({ ...this.current, pending: true, error: undefined })
    try {
      const workspace = await this.api.createWorkspace({ name })
      this.publish({
        ...this.current,
        phase: 'ready',
        pending: false,
        error: undefined,
        workspaces: [...this.current.workspaces, workspace],
      })
      return workspace
    } catch (error) {
      this.fail(error)
      return undefined
    }
  }

  async selectWorkspace(workspaceId: string): Promise<void> {
    const generation = ++this.selectionGeneration
    this.workListGeneration += 1
    this.workRefreshGeneration += 1
    this.chatGeneration += 1
    this.publish({
      ...this.current,
      phase: 'loading',
      pending: false,
      selectedWorkspaceId: workspaceId,
      employees: [],
      works: [],
      selectedWorkId: undefined,
      selectedWork: undefined,
      events: [],
      messages: [],
      discussionWorkId: undefined,
      error: undefined,
    })
    try {
      const employees = await this.api.listEmployees(workspaceId)
      if (!this.isCurrentSelection(generation, workspaceId)) return
      this.publish({ ...this.current, phase: 'ready', employees, error: undefined })
      const chatGeneration = ++this.chatGeneration
      void this.api.listMessages(workspaceId).then(conversation => {
        if (this.isCurrentSelection(generation, workspaceId) && chatGeneration === this.chatGeneration) {
          this.publish({ ...this.current, messages: conversation.messages })
        }
      }, () => undefined)
    } catch (error) {
      if (this.isCurrentSelection(generation, workspaceId)) this.fail(error)
    }
  }

  async createEmployee(input: EmployeeCreate): Promise<Employee | undefined> {
    const workspaceId = this.current.selectedWorkspaceId
    if (workspaceId === undefined) return undefined
    const generation = this.selectionGeneration
    this.publish({ ...this.current, pending: true, error: undefined })
    try {
      const employee = await this.api.createEmployee(workspaceId, input)
      if (!this.isCurrentSelection(generation, workspaceId)) return undefined
      this.publish({
        ...this.current,
        phase: 'ready',
        pending: false,
        error: undefined,
        employees: [...this.current.employees, employee],
      })
      return employee
    } catch (error) {
      if (this.isCurrentSelection(generation, workspaceId)) this.fail(error)
      return undefined
    }
  }

  async refreshMessages(): Promise<void> {
    const workspaceId = this.current.selectedWorkspaceId
    if (workspaceId === undefined) return
    const selectionGeneration = this.selectionGeneration
    const chatGeneration = ++this.chatGeneration
    const workId = this.current.discussionWorkId
    try {
      const conversation = await this.api.listMessages(workspaceId, workId)
      if (!this.isCurrentSelection(selectionGeneration, workspaceId) || chatGeneration !== this.chatGeneration) return
      this.publish({ ...this.current, phase: 'ready', messages: conversation.messages, error: undefined })
    } catch (error) {
      if (this.isCurrentSelection(selectionGeneration, workspaceId) && chatGeneration === this.chatGeneration) this.fail(error)
    }
  }

  async openDiscussion(workId: string): Promise<void> {
    this.chatGeneration += 1
    this.publish({ ...this.current, discussionWorkId: workId, messages: [], error: undefined })
    await this.refreshMessages()
  }

  async closeDiscussion(): Promise<void> {
    this.chatGeneration += 1
    this.publish({ ...this.current, discussionWorkId: undefined, messages: [], error: undefined })
    await this.refreshMessages()
  }

  async sendChatMessage(body: string, employeeIds: readonly string[]): Promise<ChatMessageProjection | undefined> {
    const workspaceId = this.current.selectedWorkspaceId
    if (workspaceId === undefined) return undefined
    const generation = this.selectionGeneration
    this.chatGeneration += 1
    this.publish({ ...this.current, pending: true, error: undefined })
    try {
      const message = await this.api.sendMessage(workspaceId, {
        body,
        mention_employee_ids: [...employeeIds],
        ...(this.current.discussionWorkId === undefined ? {} : { work_id: this.current.discussionWorkId }),
      })
      if (!this.isCurrentSelection(generation, workspaceId)) return undefined
      this.publish({ ...this.current, phase: 'ready', pending: false, messages: [...this.current.messages, message], error: undefined })
      return message
    } catch (error) {
      if (this.isCurrentSelection(generation, workspaceId)) this.fail(error)
      return undefined
    }
  }

  async retryChatExecution(executionId: string): Promise<void> {
    try {
      await this.api.retryChatExecution(executionId)
      await this.refreshMessages()
    } catch (error) {
      this.fail(error)
    }
  }

  async loadWorks(): Promise<void> {
    const workspaceId = this.current.selectedWorkspaceId
    if (workspaceId === undefined) return
    const generation = this.selectionGeneration
    const listGeneration = ++this.workListGeneration
    this.publish({ ...this.current, phase: 'loading', error: undefined })
    try {
      const works = await this.api.listWorks(workspaceId)
      if (!this.isCurrentSelection(generation, workspaceId) || listGeneration !== this.workListGeneration) return
      this.publish({ ...this.current, phase: 'ready', works, error: undefined })
    } catch (error) {
      if (this.isCurrentSelection(generation, workspaceId) && listGeneration === this.workListGeneration) {
        this.fail(error)
      }
    }
  }

  async createDirectWork(input: DirectWorkCreate): Promise<WorkProjection | undefined> {
    const workspaceId = this.current.selectedWorkspaceId
    if (workspaceId === undefined) return undefined
    const generation = this.selectionGeneration
    this.workListGeneration += 1
    this.publish({ ...this.current, pending: true, error: undefined })
    try {
      const work = await this.api.createDirectWork(workspaceId, input)
      if (!this.isCurrentSelection(generation, workspaceId)) return undefined
      const works = [...this.current.works.filter(item => item.id !== work.id), work]
      this.workRefreshGeneration += 1
      this.publish({
        ...this.current,
        phase: 'ready',
        pending: false,
        error: undefined,
        works,
        selectedWorkId: work.id,
        selectedWork: work,
        events: [],
      })
      return work
    } catch (error) {
      if (this.isCurrentSelection(generation, workspaceId)) this.fail(error)
      return undefined
    }
  }

  async createStrategyWork(input: StrategyWorkCreate): Promise<WorkProjection | undefined> {
    const workspaceId = this.current.selectedWorkspaceId
    if (workspaceId === undefined) return undefined
    const generation = this.selectionGeneration
    this.workListGeneration += 1
    this.publish({ ...this.current, pending: true, error: undefined })
    try {
      const work = await this.api.createWork(workspaceId, input)
      if (!this.isCurrentSelection(generation, workspaceId)) return undefined
      const works = [...this.current.works.filter(item => item.id !== work.id), work]
      this.workRefreshGeneration += 1
      this.publish({
        ...this.current, phase: 'ready', pending: false, error: undefined,
        works, selectedWorkId: work.id, selectedWork: work, events: [],
      })
      return work
    } catch (error) {
      if (this.isCurrentSelection(generation, workspaceId)) this.fail(error)
      return undefined
    }
  }

  async selectWork(workId: string): Promise<void> {
    this.workRefreshGeneration += 1
    this.publish({
      ...this.current,
      pending: false,
      selectedWorkId: workId,
      selectedWork: undefined,
      events: [],
      error: undefined,
    })
    await this.refreshWork(workId)
  }

  async refreshSelectedWork(): Promise<void> {
    const workId = this.current.selectedWorkId
    if (workId !== undefined) await this.refreshWork(workId)
  }

  async cancelSelectedWork(): Promise<void> {
    const workId = this.current.selectedWorkId
    if (workId === undefined) return
    const generation = ++this.workRefreshGeneration
    this.publish({ ...this.current, pending: true, error: undefined })
    try {
      const work = await this.api.cancelWork(workId)
      if (generation !== this.workRefreshGeneration || this.current.selectedWorkId !== workId) return
      this.replaceWork(work, { pending: false, phase: 'ready', error: undefined })
    } catch (error) {
      if (generation === this.workRefreshGeneration && this.current.selectedWorkId === workId) this.fail(error)
    }
  }

  applyAuthoritativeWork(work: WorkProjection): void {
    if (this.current.selectedWorkId !== work.id) return
    this.workRefreshGeneration += 1
    this.replaceWork(work, { phase: 'ready', pending: false, error: undefined })
  }

  private async refreshWork(workId: string): Promise<void> {
    const generation = ++this.workRefreshGeneration
    try {
      const [work, events] = await Promise.all([this.api.getWork(workId), this.api.listWorkEvents(workId)])
      if (generation !== this.workRefreshGeneration || this.current.selectedWorkId !== workId) return
      this.replaceWork(work, { phase: 'ready', error: undefined, events })
    } catch (error) {
      if (generation === this.workRefreshGeneration && this.current.selectedWorkId === workId) this.fail(error)
    }
  }

  private replaceWork(work: WorkProjection, changes: Partial<CompanySnapshot>): void {
    this.publish({
      ...this.current,
      ...changes,
      selectedWork: work,
      works: this.current.works.map(item => item.id === work.id ? work : item),
    })
  }

  private isCurrentSelection(generation: number, workspaceId: string): boolean {
    return generation === this.selectionGeneration && workspaceId === this.current.selectedWorkspaceId
  }

  private fail(error: unknown): void {
    const code = error instanceof ApiError ? error.code : 'company_client_error'
    this.publish({ ...this.current, phase: 'error', pending: false, error: code })
  }

  private publish(snapshot: CompanySnapshot): void {
    this.current = snapshot
    for (const listener of this.listeners) listener()
  }
}

export function useCompanyController(controller: CompanyController): CompanySnapshot {
  return useSyncExternalStore(controller.subscribe, controller.snapshot, controller.snapshot)
}

export class CompanyOverlayController {
  private active = false
  private readonly listeners = new Set<() => void>()
  snapshot = (): boolean => this.active
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  open = (): void => { this.set(true) }
  close = (): void => { this.set(false) }
  private set(active: boolean): void {
    if (this.active === active) return
    this.active = active
    for (const listener of this.listeners) listener()
  }
}
