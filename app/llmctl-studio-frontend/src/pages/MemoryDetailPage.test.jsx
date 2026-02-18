import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import MemoryDetailPage from './MemoryDetailPage'
import { getMemory, getMemoryHistory, deleteMemory, deleteMemoryArtifact } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  getMemory: vi.fn(),
  getMemoryHistory: vi.fn(),
  deleteMemory: vi.fn(),
  deleteMemoryArtifact: vi.fn(),
}))

function renderPage(initialEntry = '/memories/7') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/memories/:memoryId" element={<MemoryDetailPage />} />
        <Route path="/memories/:memoryId/artifacts/:artifactId" element={<p>Artifact detail</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('MemoryDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getMemory.mockResolvedValue({
      memory: {
        id: 7,
        description: 'release readiness memory',
        created_at: '2026-02-18 10:00',
        updated_at: '2026-02-18 10:05',
      },
    })
    getMemoryHistory.mockResolvedValue({
      request_id: 'memory-history-7-test',
      correlation_id: 'memory-7',
      artifacts: [
        {
          id: 55,
          flowchart_id: 3,
          flowchart_node_id: 9,
          flowchart_run_id: 42,
          variant_key: 'run-42-node-run-99',
          created_at: '2026-02-18 10:06',
          payload: { action: 'retrieve' },
        },
      ],
      pagination: {
        total_count: 3,
      },
    })
    deleteMemory.mockResolvedValue({ ok: true })
    deleteMemoryArtifact.mockResolvedValue({ ok: true })
  })

  test('renders artifact history and navigates via row-link', async () => {
    const { container } = renderPage()

    await waitFor(() => {
      expect(getMemory).toHaveBeenCalledWith(7)
      expect(getMemoryHistory).toHaveBeenCalledWith(7)
    })
    expect(await screen.findByText('artifact history · 3 total')).toBeInTheDocument()
    expect(screen.getByText('retrieve')).toBeInTheDocument()
    expect(screen.getByText('Triggered runs: 3')).toBeInTheDocument()
    expect(screen.getByText('Canonical memory content lives in artifacts.')).toBeInTheDocument()

    const historyRow = container.querySelector('tr.table-row-link')
    expect(historyRow).toBeTruthy()
    expect(historyRow?.getAttribute('data-href')).toBe('/memories/7/artifacts/55')

    fireEvent.click(historyRow)
    expect(await screen.findByText('Artifact detail')).toBeInTheDocument()
  })

  test('deletes a selected artifact history item only', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { container } = renderPage()

    await waitFor(() => {
      expect(getMemory).toHaveBeenCalledWith(7)
      expect(getMemoryHistory).toHaveBeenCalledWith(7)
    })

    const deleteButton = await screen.findByRole('button', { name: 'Delete artifact 55' })
    fireEvent.click(deleteButton)

    await waitFor(() => {
      expect(deleteMemoryArtifact).toHaveBeenCalledWith(7, 55)
    })
    expect(confirmSpy).toHaveBeenCalledWith('Delete this artifact history item?')
    expect(container.querySelector('tr.table-row-link')).toBeFalsy()
    confirmSpy.mockRestore()
  })

  test('applies flowchart-node history filter from query string', async () => {
    renderPage('/memories/7?flowchart_node_id=9')

    await waitFor(() => {
      expect(getMemory).toHaveBeenCalledWith(7)
      expect(getMemoryHistory).toHaveBeenCalledWith(7, { flowchartNodeId: 9 })
    })
    expect(await screen.findByText('artifact history (node 9) · 3 total')).toBeInTheDocument()
  })
})
