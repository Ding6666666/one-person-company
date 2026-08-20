import { useSyncExternalStore } from 'react'

import { ApiError, type Employee, type EmployeeCreate, ProductApi, type Workspace } from './api.js'

export interface CompanySnapshot {
  readonly phase: 'loading' | 'ready' | 'error'
  readonly pending: boolean
  readonly error: string | undefined
  readonly workspaces: readonly Workspace[]
  readonly selectedWorkspaceId: string | undefined
  readonly employees: readonly Employee[]
}

const initialSnapshot: CompanySnapshot = {
  phase: 'loading',
  pending: false,
  error: undefined,
  workspaces: [],
  selectedWorkspaceId: undefined,
  employees: [],
}

export class CompanyController {
  private current = initialSnapshot
  private readonly listeners = new Set<() => void>()
  private selectionGeneration = 0

  constructor(private readonly api: ProductApi) {}

  snapshot = (): CompanySnapshot => this.current
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  async load(): Promise<void> {
    this.publish({ ...this.current, phase: 'loading', error: undefined })
    try {
      const workspaces = await this.api.listWorkspaces()
      this.publish({ ...this.current, phase: 'ready', workspaces, error: undefined })
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
    this.publish({
      ...this.current,
      phase: 'loading',
      pending: false,
      selectedWorkspaceId: workspaceId,
      employees: [],
      error: undefined,
    })
    try {
      const employees = await this.api.listEmployees(workspaceId)
      if (!this.isCurrentSelection(generation, workspaceId)) return
      this.publish({ ...this.current, phase: 'ready', employees, error: undefined })
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
