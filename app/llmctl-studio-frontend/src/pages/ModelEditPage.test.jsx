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
    expect(await screen.findByText('Saved model Existing Profile.')).toBeInTheDocument()
    expect(screen.getByText('Model detail route')).toBeInTheDocument()
  })

  test('save stays disabled until form is both dirty and valid', async () => {
    renderPage()
    await waitFor(() => {
      expect(getModelEdit).toHaveBeenCalledWith(12)
    })

    const saveButton = screen.getByRole('button', { name: 'Save Model' })
    expect(saveButton).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: '' } })
    expect(saveButton).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Updated Profile' } })
    expect(saveButton).not.toBeDisabled()
  })

  test('advanced provider settings are collapsed by default and included in update payload', async () => {
    renderPage()
    await waitFor(() => {
      expect(getModelEdit).toHaveBeenCalledWith(12)
    })

    fireEvent.click(screen.getByText('Advanced provider settings'))
    fireEvent.change(screen.getByLabelText('Provider config JSON'), {
      target: { value: '{\n  "model_reasoning_effort": "low"\n}' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save Model' }))

    await waitFor(() => {
      expect(updateModel).toHaveBeenCalledWith(12, expect.objectContaining({
        config: expect.objectContaining({
          model: 'gpt-5-codex',
          model_reasoning_effort: 'low',
        }),
      }))
    })
  })

  test('cancel returns to model list route when there are no unsaved changes', async () => {
    renderPage()
    await waitFor(() => {
      expect(getModelEdit).toHaveBeenCalledWith(12)
    })

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(await screen.findByText('Models list route')).toBeInTheDocument()
  })

  test('prompts before leaving when there are unsaved changes', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPage()
    await waitFor(() => {
      expect(getModelEdit).toHaveBeenCalledWith(12)
    })

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Unsaved Existing Profile' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(confirmSpy).toHaveBeenCalledWith('Discard unsaved changes?')
    expect(screen.queryByText('Models list route')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save Model' })).toBeInTheDocument()
    confirmSpy.mockRestore()
  })

  test('update failures report through flash viewport', async () => {
    updateModel.mockRejectedValueOnce(new Error('Update failed in test'))
    renderPage()
    await waitFor(() => {
      expect(getModelEdit).toHaveBeenCalledWith(12)
    })

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Updated Existing Profile' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Model' }))

    expect(await screen.findByText('Update failed in test')).toBeInTheDocument()
  })
})
