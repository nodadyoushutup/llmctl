import { render, screen, waitFor, within } from '@testing-library/react'
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
        order: 'desc',
      })
    })
    expect(await screen.findByRole('heading', { name: 'Task Artifacts' })).toBeInTheDocument()
    const sidebar = screen.getByRole('complementary', { name: 'Artifact types' })
    expect(within(sidebar).getByRole('link', { name: 'Task' })).toHaveClass('is-active')
    expect(within(sidebar).getByRole('link', { name: 'Plan' })).toHaveAttribute('href', '/artifacts/type/plan')
    const row = container.querySelector('tr.table-row-link')
    expect(row).toBeTruthy()
    expect(row?.getAttribute('data-href')).toBe('/artifacts/item/101')
  })

  test('forwards flowchart and node query filters to artifact lookup', async () => {
    renderPage('/artifacts/type/decision?flowchart_id=8&flowchart_node_id=21')

    await waitFor(() => {
      expect(getNodeArtifacts).toHaveBeenCalledWith({
        limit: 50,
        offset: 0,
        artifactType: 'decision',
        flowchartId: 8,
        flowchartNodeId: 21,
        order: 'desc',
      })
    })
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

    expect(pageSection?.classList.contains('column-list-page')).toBe(true)
    expect(pageSection?.classList.contains('provider-fixed-page')).toBe(true)
    expect(panelBody?.classList.contains('workflow-fixed-panel-body')).toBe(true)
    expect(emptyState).toBeTruthy()
    expect(headerActions).toBeTruthy()
    expect(screen.queryByLabelText('Node type')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Run id')).not.toBeInTheDocument()
    const pagination = screen.getByRole('navigation', { name: 'Artifact pages' })
    expect(within(pagination).getByText('1')).toBeInTheDocument()
    expect(within(pagination).getByText('/ 1')).toBeInTheDocument()
  })
})
