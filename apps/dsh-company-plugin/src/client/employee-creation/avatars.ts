import type { RoleTemplateKey } from './types.js'
import algorithmEngineer from '../assets/employee-avatars/algorithm-engineer.png'
import backendEngineer from '../assets/employee-avatars/backend-engineer.png'
import custom from '../assets/employee-avatars/custom.png'
import frontendEngineer from '../assets/employee-avatars/frontend-engineer.png'
import fullstackEngineer from '../assets/employee-avatars/fullstack-engineer.png'
import productManager from '../assets/employee-avatars/product-manager.png'
import testEngineer from '../assets/employee-avatars/test-engineer.png'

export const employeeAvatars: Readonly<Record<RoleTemplateKey, string>> = {
  'product-manager': productManager,
  'frontend-engineer': frontendEngineer,
  'backend-engineer': backendEngineer,
  'fullstack-engineer': fullstackEngineer,
  'algorithm-engineer': algorithmEngineer,
  'test-engineer': testEngineer,
  custom,
}
