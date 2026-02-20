import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import FlashProvider from '../components/FlashProvider'
import ModelEditPage from './ModelEditPage'
import { getModelEdit, updateModel } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  getModelEdit: vi.fn(),
  updateModel: vi.fn(),
}))

function renderPage(initialEntry = '/models/12/edit') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <FlashProvider>
        <Routes>
          <Route path="/models/:modelId/edit" element={<ModelEditPage />} />
          <Route path="/models/:modelId" element={<p>Model detail route</p>} />
          <Route path="/models" element={<p>Models list route</p>} />
        </Routes>
      </FlashProvider>
    </MemoryRouter>,
  )
}

describe('ModelEditPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getModelEdit.mockResolvedValue({
      model: {
        id: 12,
        name: 'Existing Profile',
        provider: 'codex',
        config: { model: 'gpt-5-codex' },
        config_json: '{\n  "model": "gpt-5-codex"\n}',
      },
      provider_options: [
        { value: 'codex', label: 'Codex' },
        { value: 'claude', label: 'Claude' },
      ],
      model_options: {
        codex: ['gpt-5-codex', 'gpt-5'],
        claude: ['claude-4', 'claude-3.7-sonnet'],
      },
    })
    updateModel.mockResolvedValue({ ok: true })
  })

  test('loads provider-scoped model selection and switches control type', async () => {
    renderPage()
    await waitFor(() => {
      expect(getModelEdit).toHaveBeenCalledWith(12)
    })

    const providerSelect = screen.getByLabelText('Provider')
    const codexModelSelect = screen.getByLabelText('Codex model')
    expect(codexModelSelect.tagName).toBe('SELECT')
    expect(codexModelSelect).toHaveValue('gpt-5-codex')

    fireEvent.change(providerSelect, { target: { value: 'claude' } })

    const claudeModelInput = screen.getByLabelText('Claude model')
    expect(claudeModelInput.tagName).toBe('INPUT')
    expect(claudeModelInput).toHaveValue('claude-4')
    expect(claudeModelInput).toHaveAttribute('list', 'edit-model-options')
  })

  test('persists selected model value in update payload', async () => {
    renderPage()
    await waitFor(() => {
      expect(getModelEdit).toHaveBeenCalledWith(12)
    })

    fireEvent.change(screen.getByLabelText('Codex model'), { target: { value: 'gpt-5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Model' }))

    await waitFor(() => {
      expect(updateModel).toHaveBeenCalledWith(12, expect.objectContaining({
        provider: 'codex',
        config: expect.objectContaining({
          model: 'gpt-5',
        }),
      }))
    })
  })
})
