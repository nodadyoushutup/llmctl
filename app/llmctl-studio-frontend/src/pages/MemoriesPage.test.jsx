import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import MemoriesPage from './MemoriesPage'
import { getMemories } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  getMemories: vi.fn(),
}))

function renderPage(initialEntry = '/memories') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/memories" element={<MemoriesPage />} />
        <Route path="/memories/:memoryId" element={<p>Memory detail</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('MemoriesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getMemories.mockResolvedValue({
      memories: [
        {
          id: 7,
          description: 'release-readiness memory',
          flowchart_id: 3,
          flowchart_name: 'Release Readiness',
          flowchart_node_id: 9,
          created_at: '2026-02-18 10:00',
        },
      ],
      pagination: {
        page: 1,
        per_page: 20,
        total_pages: 1,
        items: [{ type: 'page', page: 1, label: '1' }],
      },
    })
  })

  test('renders flowchart column and node-scoped memory detail href', async () => {
    const { container } = renderPage()

    await waitFor(() => {
      expect(getMemories).toHaveBeenCalledWith({ page: 1, perPage: 20 })
    })
    expect(await screen.findByText('Flowchart')).toBeInTheDocument()
    expect(screen.getByText('Release Readiness')).toBeInTheDocument()

    const row = container.querySelector('tr.table-row-link')
    expect(row).toBeTruthy()
    expect(row?.getAttribute('data-href')).toBe('/memories/7?flowchart_node_id=9')
  })
})
