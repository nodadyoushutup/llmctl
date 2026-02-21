import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { forwardRef, useEffect, useImperativeHandle } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import FlashProvider from '../components/FlashProvider'
import FlowchartDetailPage from './FlowchartDetailPage'
import {
  getFlowchartEdit,
  getFlowchartGraph,
  getFlowchartHistory,
  getFlowchartRuntime,
  runFlowchart,
} from '../lib/studioApi'

const mountSpy = vi.fn()
const unmountSpy = vi.fn()

vi.mock('../components/FlowchartWorkspaceEditor', () => {
  const MockFlowchartWorkspaceEditor = forwardRef(function MockFlowchartWorkspaceEditor(_props, ref) {
    useImperativeHandle(ref, () => ({
      applyServerGraph: () => false,
      validateBeforeSave: () => true,
    }), [])

    useEffect(() => {
      mountSpy()
      return () => {
        unmountSpy()
      }
    }, [])

    return <div data-testid="flowchart-workspace-editor">mock workspace</div>
  })
  MockFlowchartWorkspaceEditor.displayName = 'MockFlowchartWorkspaceEditor'
  return { default: MockFlowchartWorkspaceEditor }
})

vi.mock('../lib/studioApi', () => ({
  cancelFlowchartRun: vi.fn(),
  deleteFlowchart: vi.fn(),
  getFlowchartEdit: vi.fn(),
  getFlowchartGraph: vi.fn(),
  getFlowchartHistory: vi.fn(),
  getFlowchartRuntime: vi.fn(),
  runFlowchart: vi.fn(),
  updateFlowchartGraph: vi.fn(),
  validateFlowchart: vi.fn(),
}))

function renderPage(initialEntry = '/flowcharts/9') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <FlashProvider>
        <Routes>
          <Route path="/flowcharts/:flowchartId" element={<FlowchartDetailPage />} />
          <Route path="/flowcharts" element={<p>Flowcharts list route</p>} />
        </Routes>
      </FlashProvider>
    </MemoryRouter>,
  )
}

describe('FlowchartDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getFlowchartGraph.mockResolvedValue({
      nodes: [{ id: 1, node_type: 'start', x: 120, y: 120 }],
      edges: [],
      validation: { valid: true, errors: [] },
    })
    getFlowchartHistory.mockResolvedValue({
      flowchart: { id: 9, name: 'Release Workflow', max_runtime_minutes: 60, max_parallel_nodes: 2 },
      runs: [],
    })
    getFlowchartEdit.mockResolvedValue({ catalog: null, node_types: ['start', 'task', 'end'] })
    getFlowchartRuntime.mockResolvedValue({ active_run_id: null, active_run_status: null, running_node_ids: [] })
    runFlowchart.mockResolvedValue({ flowchart_run: { id: 42 } })
  })

  test('running a flowchart does not remount the workspace editor', async () => {
    renderPage()

    await waitFor(() => {
      expect(getFlowchartGraph).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(screen.queryByText('Loading flowchart...')).not.toBeInTheDocument()
    })
    const mountsBeforeRun = mountSpy.mock.calls.length
    const unmountsBeforeRun = unmountSpy.mock.calls.length

    fireEvent.click(screen.getByRole('button', { name: 'Run flowchart' }))

    await waitFor(() => {
      expect(runFlowchart).toHaveBeenCalledWith(9)
    })
    await waitFor(() => {
      expect(getFlowchartGraph).toHaveBeenCalledTimes(2)
    })
    expect(mountSpy.mock.calls.length).toBe(mountsBeforeRun)
    expect(unmountSpy.mock.calls.length).toBe(unmountsBeforeRun)
  })
})
