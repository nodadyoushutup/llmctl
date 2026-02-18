import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import MemoryDetailPage from './MemoryDetailPage'
import { getMemory, getMemoryHistory, deleteMemory } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  getMemory: vi.fn(),
  getMemoryHistory: vi.fn(),
  deleteMemory: vi.fn(),
}))

function renderPage(initialEntry = '/memories/7') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/memories/:memoryId" element={<MemoryDetailPage />} />
        <Route path="/flowcharts/runs/:runId" element={<p>Run detail</p>} />
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
    })
    deleteMemory.mockResolvedValue({ ok: true })
  })

  test('renders artifact history and navigates via row-link', async () => {
    const { container } = renderPage()

    await waitFor(() => {
      expect(getMemory).toHaveBeenCalledWith(7)
      expect(getMemoryHistory).toHaveBeenCalledWith(7)
    })
    expect(await screen.findByText('artifact history')).toBeInTheDocument()
    expect(screen.getByText('retrieve')).toBeInTheDocument()

    const historyRow = container.querySelector('tr.table-row-link')
    expect(historyRow).toBeTruthy()
    expect(historyRow?.getAttribute('data-href')).toBe('/flowcharts/runs/42')

    fireEvent.click(historyRow)
    expect(await screen.findByText('Run detail')).toBeInTheDocument()
  })
})
