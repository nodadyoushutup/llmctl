import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import FlashProvider from '../components/FlashProvider'
import QuickNodePage from './QuickNodePage'
import { createQuickNode, getQuickNodeMeta, updateQuickNodeDefaults } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  createQuickNode: vi.fn(),
  getQuickNodeMeta: vi.fn(),
  updateQuickNodeDefaults: vi.fn(),
}))

function renderPage(initialEntry = '/quick') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <FlashProvider>
        <Routes>
          <Route path="/quick" element={<QuickNodePage />} />
          <Route path="/nodes/:nodeId" element={<p>Node detail route</p>} />
          <Route path="/nodes" element={<p>Nodes list route</p>} />
        </Routes>
      </FlashProvider>
    </MemoryRouter>,
  )
}

describe('QuickNodePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getQuickNodeMeta.mockResolvedValue({
      agents: [{ id: 1, name: 'Agent A' }],
      models: [{ id: 3, name: 'GPT-5', provider: 'codex' }],
      mcp_servers: [{ id: 5, name: 'GitHub MCP', server_key: 'github' }],
      rag_collections: [],
      default_agent_id: null,
      default_model_id: 3,
      selected_mcp_server_ids: [],
      selected_rag_collections: [],
    })
    createQuickNode.mockResolvedValue({ task_id: 88 })
    updateQuickNodeDefaults.mockResolvedValue({
      quick_default_settings: {
        default_agent_id: null,
        default_model_id: 3,
        default_mcp_server_ids: [5],
        default_rag_collections: [],
      },
    })
  })

  test('saves defaults and submits using MCP selection without manual integrations', async () => {
    renderPage()

    await waitFor(() => {
      expect(getQuickNodeMeta).toHaveBeenCalledTimes(1)
    })

    expect(screen.getByText('Integrations are auto-applied from selected MCP servers.')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText(/GitHub MCP/i))
    fireEvent.click(screen.getByRole('button', { name: 'Save quick defaults' }))

    await waitFor(() => {
      expect(updateQuickNodeDefaults).toHaveBeenCalledTimes(1)
    })
    const defaultsPayload = updateQuickNodeDefaults.mock.calls[0][0]
    expect(defaultsPayload.defaultMcpServerIds).toEqual([5])
    expect(defaultsPayload.defaultIntegrationKeys).toBeUndefined()

    fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Summarize open PRs' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send to CLI' }))

    await waitFor(() => {
      expect(createQuickNode).toHaveBeenCalledTimes(1)
    })
    const createPayload = createQuickNode.mock.calls[0][0]
    expect(createPayload).toEqual(expect.objectContaining({
      prompt: 'Summarize open PRs',
      modelId: 3,
      mcpServerIds: [5],
    }))
    expect(createPayload.integrationKeys).toBeUndefined()
    expect(await screen.findByText('Node detail route')).toBeInTheDocument()
  })
})
