import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import FlashProvider from '../components/FlashProvider'
import NodeNewPage from './NodeNewPage'
import { createNode, getNodeMeta } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  createNode: vi.fn(),
  getNodeMeta: vi.fn(),
}))

function renderPage(initialEntry = '/nodes/new') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <FlashProvider>
        <Routes>
          <Route path="/nodes/new" element={<NodeNewPage />} />
          <Route path="/nodes/:nodeId" element={<p>Node detail route</p>} />
          <Route path="/nodes" element={<p>Nodes list route</p>} />
        </Routes>
      </FlashProvider>
    </MemoryRouter>,
  )
}

describe('NodeNewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getNodeMeta.mockResolvedValue({
      agents: [{ id: 1, name: 'Agent A' }],
      scripts: [],
      script_type_fields: {},
      script_type_choices: [],
      mcp_servers: [{ id: 7, name: 'GitHub MCP', server_key: 'github' }],
      selected_mcp_server_ids: [],
    })
    createNode.mockResolvedValue({ task_id: 55 })
  })

  test('submits selected MCP servers and does not use manual integration keys', async () => {
    renderPage()

    await waitFor(() => {
      expect(getNodeMeta).toHaveBeenCalledTimes(1)
    })

    expect(screen.getByText('Integrations are auto-applied from selected MCP servers.')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Agent'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Create release plan' } })
    fireEvent.click(screen.getByLabelText(/GitHub MCP/i))
    fireEvent.click(screen.getByRole('button', { name: 'Queue Node' }))

    await waitFor(() => {
      expect(createNode).toHaveBeenCalledTimes(1)
    })

    const createPayload = createNode.mock.calls[0][0]
    expect(createPayload).toEqual(expect.objectContaining({
      agentId: 1,
      prompt: 'Create release plan',
      mcpServerIds: [7],
    }))
    expect(createPayload.integrationKeys).toBeUndefined()
    expect(await screen.findByText('Node detail route')).toBeInTheDocument()
  })
})
