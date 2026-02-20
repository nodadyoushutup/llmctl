import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import FlashProvider from '../components/FlashProvider'
import ModelNewPage from './ModelNewPage'
import { createModel, getModelMeta } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  createModel: vi.fn(),
  getModelMeta: vi.fn(),
}))

function renderPage(initialEntry = '/models/new') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <FlashProvider>
        <Routes>
          <Route path="/models/new" element={<ModelNewPage />} />
          <Route path="/models/:modelId" element={<p>Model detail route</p>} />
          <Route path="/models" element={<p>Models list route</p>} />
        </Routes>
      </FlashProvider>
    </MemoryRouter>,
  )
}

describe('ModelNewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getModelMeta.mockResolvedValue({
      provider_options: [
        { value: 'codex', label: 'Codex' },
        { value: 'claude', label: 'Claude' },
      ],
      model_options: {
        codex: ['gpt-5-codex', 'gpt-5'],
        claude: ['claude-4', 'claude-3.7-sonnet'],
      },
    })
    createModel.mockResolvedValue({
      model: { id: 33 },
    })
  })

  test('switches model input mode and options by provider', async () => {
    renderPage()
    await waitFor(() => {
      expect(getModelMeta).toHaveBeenCalledTimes(1)
    })

    const providerSelect = screen.getByLabelText('Provider')
    const codexModelSelect = screen.getByLabelText('Codex model')
    expect(codexModelSelect.tagName).toBe('SELECT')
    expect(codexModelSelect).toHaveValue('gpt-5-codex')

    fireEvent.change(providerSelect, { target: { value: 'claude' } })

    const claudeModelInput = screen.getByLabelText('Claude model')
    expect(claudeModelInput.tagName).toBe('INPUT')
    expect(claudeModelInput).toHaveValue('claude-4')
    expect(claudeModelInput).toHaveAttribute('list', 'new-model-options')
  })

  test('submits selected provider model in config payload', async () => {
    renderPage()
    await waitFor(() => {
      expect(getModelMeta).toHaveBeenCalledTimes(1)
    })

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Primary Codex' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Model' }))

    await waitFor(() => {
      expect(createModel).toHaveBeenCalledWith(expect.objectContaining({
        name: 'Primary Codex',
        provider: 'codex',
        config: expect.objectContaining({
          model: 'gpt-5-codex',
        }),
      }))
    })
  })
})
