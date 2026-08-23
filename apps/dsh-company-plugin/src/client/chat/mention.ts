import type { Employee } from '../api.js'

export function filterMentionCandidates(employees: readonly Employee[], query: string): Employee[] {
  const needle = query.trim().toLocaleLowerCase()
  if (!needle) return employees.filter(employee => employee.status === 'active')
  return employees.filter(employee => employee.status === 'active' && [
    employee.display_name,
    employee.revision.work_type,
    employee.revision.responsibility,
  ].some(value => value.toLocaleLowerCase().includes(needle)))
}

export function mentionEmployeeIds(employees: readonly Employee[]): string[] {
  return [...new Set(employees.map(employee => employee.id))]
}
