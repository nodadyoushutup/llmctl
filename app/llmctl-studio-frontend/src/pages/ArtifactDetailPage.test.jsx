import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import ArtifactDetailPage from './ArtifactDetailPage'
import { getMemoryArtifact, getMilestoneArtifact, getPlanArtifact } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  getMemoryArtifact: vi.fn(),
  getMilestoneArtifact: vi.fn(),
  getPlanArtifact: vi.fn(),
}))

function renderPage(initialEntry) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/memories/:memoryId/artifacts/:artifactId" element={<ArtifactDetailPage />} />
        <Route path="/plans/:planId/artifacts/:artifactId" element={<ArtifactDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ArtifactDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getMemoryArtifact.mockResolvedValue({
      item: {
        id: 55,
        artifact_type: 'memory',
        flowchart_id: 3,
        flowchart_node_id: 9,
        flowchart_run_id: 42,
        flowchart_run_node_id: 88,
        variant_key: 'run-42-node-run-88',
        payload: { action: 'retrieve', value: 'sample' },
        request_id: 'req-memory-artifact',
        correlation_id: 'corr-memory-artifact',
        created_at: '2026-02-18 11:00',
        updated_at: '2026-02-18 11:01',
      },
    })
    getPlanArtifact.mockResolvedValue({
      item: {
        id: 17,
        artifact_type: 'plan',
        flowchart_id: 4,
        flowchart_node_id: 10,
        flowchart_run_id: 51,
        flowchart_run_node_id: 92,
        variant_key: 'run-51-node-run-92',
        payload: { action: 'create_or_update_plan' },
        created_at: '2026-02-18 12:00',
        updated_at: '2026-02-18 12:05',
      },
    })
  })

  test('loads memory artifact details for memory route', async () => {
    renderPage('/memories/7/artifacts/55')

    await waitFor(() => {
      expect(getMemoryArtifact).toHaveBeenCalledWith(7, 55)
    })
    expect(await screen.findByText('Artifact 55')).toBeInTheDocument()
    expect(screen.getByText('retrieve')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'run detail' })).toHaveAttribute('href', '/flowcharts/runs/42')
    expect(getMilestoneArtifact).not.toHaveBeenCalled()
    expect(getPlanArtifact).not.toHaveBeenCalled()
  })

  test('loads plan artifact details for plan route', async () => {
    renderPage('/plans/5/artifacts/17')

    await waitFor(() => {
      expect(getPlanArtifact).toHaveBeenCalledWith(5, 17)
    })
    expect(await screen.findByText('Artifact 17')).toBeInTheDocument()
    expect(getMemoryArtifact).not.toHaveBeenCalled()
    expect(getMilestoneArtifact).not.toHaveBeenCalled()
  })
})
