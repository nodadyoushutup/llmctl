import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import FlashProvider from '../components/FlashProvider'
import SettingsProviderPage from './SettingsProviderPage'
import {
  getSettingsProvider,
  updateSettingsProviderClaude,
  updateSettingsProviderCodex,
  updateSettingsProviderControls,
  updateSettingsProviderGemini,
  updateSettingsProviderVllmLocal,
  updateSettingsProviderVllmRemote,
} from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  getSettingsProvider: vi.fn(),
  updateSettingsProviderClaude: vi.fn(),
  updateSettingsProviderCodex: vi.fn(),
  updateSettingsProviderControls: vi.fn(),
  updateSettingsProviderGemini: vi.fn(),
  updateSettingsProviderVllmLocal: vi.fn(),
  updateSettingsProviderVllmRemote: vi.fn(),
}))

function renderPage(initialEntry = '/settings/provider/gemini') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <FlashProvider>
        <Routes>
          <Route path="/settings/provider" element={<SettingsProviderPage />} />
          <Route path="/settings/provider/:section" element={<SettingsProviderPage />} />
        </Routes>
      </FlashProvider>
    </MemoryRouter>,
  )
}

function buildPayload() {
  return {
    provider_summary: { provider: 'gemini' },
    provider_details: [{ id: 'gemini', label: 'Gemini', enabled: true }],
    provider_sections: [
      { id: 'controls', label: 'Controls' },
      { id: 'gemini', label: 'Gemini' },
    ],
    codex_settings: { api_key: '' },
    gemini_settings: {
      api_key: 'existing-key',
      use_vertex_ai: true,
      project: 'vertex-proj',
      location: 'us-central1',
    },
    claude_settings: { api_key: '' },
    vllm_local_settings: { model: '', huggingface: { token: '' }, models: [] },
    vllm_remote_settings: { base_url: '', api_key: '', model: '', models: [] },
  }
}

describe('SettingsProviderPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    const payload = buildPayload()
    getSettingsProvider.mockResolvedValue(payload)
    updateSettingsProviderControls.mockResolvedValue({ ok: true })
    updateSettingsProviderCodex.mockResolvedValue({ ok: true })
    updateSettingsProviderGemini.mockResolvedValue({ ok: true })
    updateSettingsProviderClaude.mockResolvedValue({ ok: true })
    updateSettingsProviderVllmLocal.mockResolvedValue({ ok: true })
    updateSettingsProviderVllmRemote.mockResolvedValue({ ok: true })
  })

  test('gemini save sends vertex fields from provider settings form', async () => {
    renderPage('/settings/provider/gemini')

    await screen.findByRole('button', { name: 'Save Gemini' })
    expect(screen.getByLabelText('Use Vertex AI')).toBeChecked()
    expect(screen.getByLabelText('Vertex project')).toHaveValue('vertex-proj')
    expect(screen.getByLabelText('Vertex location')).toHaveValue('us-central1')

    fireEvent.change(screen.getByLabelText('Gemini API key'), { target: { value: 'new-key' } })
    fireEvent.click(screen.getByLabelText('Use Vertex AI'))
    fireEvent.change(screen.getByLabelText('Vertex project'), { target: { value: 'proj-2' } })
    fireEvent.change(screen.getByLabelText('Vertex location'), { target: { value: 'europe-west4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Gemini' }))

    await waitFor(() => {
      expect(updateSettingsProviderGemini).toHaveBeenCalledWith({
        apiKey: 'new-key',
        useVertexAi: false,
        project: 'proj-2',
        location: 'europe-west4',
      })
    })
  })
})
