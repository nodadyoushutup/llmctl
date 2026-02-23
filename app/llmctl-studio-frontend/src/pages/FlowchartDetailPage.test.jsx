import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { forwardRef, useEffect, useImperativeHandle } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import FlashProvider from '../components/FlashProvider'
import FlowchartDetailPage from './FlowchartDetailPage'
import {
  createQuickNode,
  getFlowchartEdit,
  getFlowchartGraph,
  getFlowchartHistory,
  getFlowchartRuntime,
  runFlowchart,
} from '../lib/studioApi'

const mountSpy = vi.fn()
const unmountSpy = vi.fn()

vi.mock('../components/FlowchartWorkspaceEditor', () => {
  const MockFlowchartWorkspaceEditor = forwardRef(function MockFlowchartWorkspaceEditor(props, ref) {
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

    return (
      <div>
        <div data-testid="flowchart-workspace-editor-actions">{props.panelActions}</div>
        <button
          type="button"
          onClick={() => props.onRunFromNode?.({
            persistedId: 11,
            node_type: 'task',
            title: 'Deploy Node',
          })}
        >
          Mock Run From Node
        </button>
        <button
          type="button"
          onClick={() => props.onQuickNodeFromNode?.({
            persistedId: 11,
            node_type: 'task',
            title: 'Deploy Node',
            model_id: 5,
            mcp_server_ids: [7],
            config: { task_prompt: 'Deploy release build', collections: ['ops'] },
          })}
        >
          Mock Quick Node
        </button>
        <div data-testid="flowchart-workspace-editor">mock workspace</div>
      </div>
    )
  })
  MockFlowchartWorkspaceEditor.displayName = 'MockFlowchartWorkspaceEditor'
  return { default: MockFlowchartWorkspaceEditor }
})

vi.mock('../lib/studioApi', () => ({
  cancelFlowchartRun: vi.fn(),
  createQuickNode: vi.fn(),
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
          <Route path="/nodes" element={<p>Nodes list route</p>} />
          <Route path="/nodes/:nodeId" element={<p>Node detail route</p>} />
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
    createQuickNode.mockResolvedValue({ task_id: 88 })
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

  test('run from node uses start_node_id override', async () => {
    renderPage()

    await waitFor(() => {
      expect(getFlowchartGraph).toHaveBeenCalledTimes(1)
    })

    fireEvent.click(screen.getByRole('button', { name: 'Mock Run From Node' }))

    await waitFor(() => {
      expect(runFlowchart).toHaveBeenCalledWith(9, { startNodeId: 11 })
    })
  })

  test('quick node from selected node creates and routes to node detail', async () => {
    renderPage()

    await waitFor(() => {
      expect(getFlowchartGraph).toHaveBeenCalledTimes(1)
    })

    fireEvent.click(screen.getByRole('button', { name: 'Mock Quick Node' }))

    await waitFor(() => {
      expect(createQuickNode).toHaveBeenCalledWith({
        prompt: 'Deploy release build',
        modelId: 5,
        mcpServerIds: [7],
        ragCollections: ['ops'],
      })
    })
    await waitFor(() => {
      expect(screen.getByText('Node detail route')).toBeInTheDocument()
    })
  })
})
