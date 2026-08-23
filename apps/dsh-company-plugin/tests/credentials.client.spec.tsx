// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  CredentialPanel,
  type CompanyCredentials,
} from '../src/client/CredentialPanel.js'
import { translate } from '../src/client/locales.js'

function credentials(
  view: { configured: boolean; source?: string; writable: boolean },
): CompanyCredentials & { set: ReturnType<typeof vi.fn>; unset: ReturnType<typeof vi.fn> } {
  return {
    describe: vi.fn(async () => view),
    set: vi.fn(async () => undefined),
    unset: vi.fn(async () => undefined),
  }
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('DeepSeek credential panel', () => {
  it('never renders a stored value and clears the replacement after save', async () => {
    const api = credentials({ configured: true, source: 'file', writable: true })
    const user = userEvent.setup()
    render(<CredentialPanel credentials={api} t={translate('zh')} />)

    expect(await screen.findByText('DeepSeek API 已配置')).toBeInTheDocument()
    const input = screen.getByLabelText('新的 API Key')
    expect(input).toHaveValue('')
    expect(screen.queryByDisplayValue(/stored|existing/u)).not.toBeInTheDocument()

    await user.type(input, 'synthetic-test-key')
    await user.click(screen.getByRole('button', { name: '保存新密钥' }))

    await waitFor(() => expect(api.set).toHaveBeenCalledWith('synthetic-test-key'))
    expect(input).toHaveValue('')
  })

  it('disables changes when the environment is authoritative', async () => {
    const api = credentials({ configured: true, source: 'env', writable: false })
    render(<CredentialPanel credentials={api} t={translate('zh')} />)

    expect(await screen.findByText('由环境变量管理')).toBeInTheDocument()
    expect(screen.getByLabelText('新的 API Key')).toBeDisabled()
    expect(screen.getByRole('button', { name: '清除当前配置' })).toBeDisabled()
  })

  it('requires confirmation before clearing a writable credential', async () => {
    const api = credentials({ configured: true, source: 'file', writable: true })
    vi.spyOn(globalThis, 'confirm').mockReturnValue(false)
    render(<CredentialPanel credentials={api} t={translate('zh')} />)
    await screen.findByText('DeepSeek API 已配置')

    fireEvent.click(screen.getByRole('button', { name: '清除当前配置' }))
    expect(api.unset).not.toHaveBeenCalled()

    vi.mocked(globalThis.confirm).mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: '清除当前配置' }))
    await waitFor(() => expect(api.unset).toHaveBeenCalledOnce())
  })
})
