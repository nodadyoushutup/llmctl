import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import ArtifactExplorerPage from './ArtifactExplorerPage'
import { getNodeArtifacts } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  getNodeArtifacts: vi.fn(),
}))

function renderPage(initialEntry = '/artifacts/type/task') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/artifacts/type/:artifactType" element={<ArtifactExplorerPage />} />
        <Route path="/artifacts/item/:artifactId" element={<p>Artifact detail</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ArtifactExplorerPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getNodeArtifacts.mockResolvedValue({
      total_count: 1,
      items: [
        {
          id: 101,
          artifact_type: 'task',
          node_type: 'task',
          flowchart_id: 5,
          flowchart_run_id: 63,
          ref_id: null,
          payload: { action: 'execute_task_prompt' },
          created_at: '2026-02-19 10:00',
        },
      ],
    })
  })

  test('loads type-scoped artifacts and renders row-link to detail', async () => {
    const { container } = renderPage('/artifacts/type/task')
    await waitFor(() => {
      expect(getNodeArtifacts).toHaveBeenCalledWith({
        limit: 50,
        offset: 0,
        artifactType: 'task',
        nodeType: '',
        flowchartRunId: null,
        order: 'desc',
      })
    })
    expect(await screen.findByRole('heading', { name: 'Task Artifacts' })).toBeInTheDocument()
    const row = container.querySelector('tr.table-row-link')
    expect(row).toBeTruthy()
    expect(row?.getAttribute('data-href')).toBe('/artifacts/item/101')
  })

  test('keeps fixed-height layout and renders centered empty state when list is empty', async () => {
    getNodeArtifacts.mockResolvedValueOnce({
      total_count: 0,
      items: [],
    })
    const { container } = renderPage('/artifacts/type/milestone')

    expect(await screen.findByText('No artifacts found for this filter set.')).toBeInTheDocument()
    const pageSection = container.querySelector('section[aria-label="Milestone Artifacts"]')
    const panelBody = container.querySelector('.panel-card-body')
    const emptyState = container.querySelector('.artifact-explorer-empty-state')
    const headerActions = container.querySelector('.panel-header .artifact-explorer-header-actions')

    expect(pageSection?.classList.contains('workflow-fixed-page')).toBe(true)
    expect(panelBody?.classList.contains('workflow-fixed-panel-body')).toBe(true)
    expect(emptyState).toBeTruthy()
    expect(headerActions).toBeTruthy()
    expect(screen.getByRole('button', { name: 'filter' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'reset' })).toBeInTheDocument()
  })
})
