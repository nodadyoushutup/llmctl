import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createRef } from 'react'
import { describe, expect, test, vi } from 'vitest'
import FlowchartWorkspaceEditor from './FlowchartWorkspaceEditor'

function lastGraphPayload(mockFn) {
  const call = mockFn.mock.calls[mockFn.mock.calls.length - 1]
  return call ? call[0] : null
}

describe('FlowchartWorkspaceEditor start positioning', () => {
  test('adds a missing start node centered in the workspace', async () => {
    const onGraphChange = vi.fn()

    render(<FlowchartWorkspaceEditor onGraphChange={onGraphChange} />)

    await waitFor(() => {
      expect(onGraphChange).toHaveBeenCalled()
    })

    const payload = lastGraphPayload(onGraphChange)
    const startNode = payload?.nodes?.find((node) => node.node_type === 'start')
    expect(startNode).toMatchObject({ x: -54, y: -54 })
  })

  test('recenters legacy start-only graphs saved at 0,0', async () => {
    const onGraphChange = vi.fn()

    render(
      <FlowchartWorkspaceEditor
        initialNodes={[{ id: 1, node_type: 'start', x: 0, y: 0 }]}
        initialEdges={[]}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(onGraphChange).toHaveBeenCalled()
    })

    const payload = lastGraphPayload(onGraphChange)
    const startNode = payload?.nodes?.find((node) => node.id === 1)
    expect(startNode).toMatchObject({ x: -54, y: -54 })
  })

  test('keeps existing start coordinates when the graph has multiple nodes', async () => {
    const onGraphChange = vi.fn()

    render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 0, y: 0 },
          { id: 2, node_type: 'task', x: 320, y: 200 },
        ]}
        initialEdges={[]}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(onGraphChange).toHaveBeenCalled()
    })

    const payload = lastGraphPayload(onGraphChange)
    const startNode = payload?.nodes?.find((node) => node.id === 1)
    expect(startNode).toMatchObject({ x: 0, y: 0 })
  })

  test('hides start from the node bar palette', () => {
    const { container } = render(<FlowchartWorkspaceEditor />)
    const paletteLabels = Array.from(container.querySelectorAll('.flow-ws-sidebar .flow-ws-palette-item'))
      .map((button) => String(button.textContent || '').trim().toLowerCase())

    expect(paletteLabels).not.toContain('start')
    expect(paletteLabels).toContain('end')
  })

  test('renders legacy connector geometry and edge arrow marker', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'task', x: 500, y: 220 },
          { id: 3, node_type: 'memory', x: 900, y: 220 },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 2, source_handle_id: 'r1', target_handle_id: 'l1' }]}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"] .flow-ws-node-connector')).toBeTruthy()
    })

    expect(container.querySelectorAll('.flow-ws-node[data-node-token="id:1"] .flow-ws-node-connector')).toHaveLength(4)
    expect(container.querySelectorAll('.flow-ws-node[data-node-token="id:2"] .flow-ws-node-connector')).toHaveLength(12)
    expect(container.querySelectorAll('.flow-ws-node[data-node-token="id:3"] .flow-ws-node-connector')).toHaveLength(8)
    expect(container.querySelector('marker#flow-ws-arrow')).toBeTruthy()
  })

  test('aligns rag connectors to trapezoid edge geometry', async () => {
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'rag', x: 500, y: 220 },
        ]}
        initialEdges={[]}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"] .flow-ws-node-connector[data-handle-id="l1"]')).toBeTruthy()
    })

    const nodeWidth = 190
    const leftMid = container.querySelector('.flow-ws-node[data-node-token="id:2"] .flow-ws-node-connector[data-handle-id="l1"]')
    const topLeft = container.querySelector('.flow-ws-node[data-node-token="id:2"] .flow-ws-node-connector[data-handle-id="t1"]')
    const bottomLeft = container.querySelector('.flow-ws-node[data-node-token="id:2"] .flow-ws-node-connector[data-handle-id="b1"]')
    const rightMid = container.querySelector('.flow-ws-node[data-node-token="id:2"] .flow-ws-node-connector[data-handle-id="r1"]')

    expect(leftMid).toBeTruthy()
    expect(topLeft).toBeTruthy()
    expect(bottomLeft).toBeTruthy()
    expect(rightMid).toBeTruthy()
    expect(parseFloat(topLeft.style.left)).toBeCloseTo(0, 1)
    expect(parseFloat(leftMid.style.left)).toBeCloseTo(nodeWidth * 0.07, 1)
    expect(parseFloat(bottomLeft.style.left)).toBeCloseTo(nodeWidth * 0.14, 1)
    expect(parseFloat(rightMid.style.left)).toBeCloseTo(nodeWidth * 0.93, 1)
  })

  test('supports click-to-click connector creation', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'task', x: 500, y: 220 },
        ]}
        initialEdges={[]}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:1"] .flow-ws-node-connector[data-handle-id="r1"]')).toBeTruthy()
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"] .flow-ws-node-connector[data-handle-id="l1"]')).toBeTruthy()
    })

    const sourceConnector = container.querySelector('.flow-ws-node[data-node-token="id:1"] .flow-ws-node-connector[data-handle-id="r1"]')
    const targetConnector = container.querySelector('.flow-ws-node[data-node-token="id:2"] .flow-ws-node-connector[data-handle-id="l1"]')
    expect(sourceConnector).toBeTruthy()
    expect(targetConnector).toBeTruthy()

    fireEvent.pointerDown(sourceConnector, { button: 0, clientX: 200, clientY: 200 })
    fireEvent.pointerUp(window, { button: 0, clientX: 200, clientY: 200 })
    fireEvent.pointerDown(targetConnector, { button: 0, clientX: 500, clientY: 220 })
    fireEvent.pointerUp(window, { button: 0, clientX: 500, clientY: 220 })

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      expect(payload?.edges).toHaveLength(1)
      expect(payload?.edges?.[0]).toMatchObject({ source_handle_id: 'r1', target_handle_id: 'l1' })
    })
  })

  test('adds and drags connector bend points for selected edges', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'task', x: 520, y: 220, config: { task_prompt: 'run' } },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 2, source_handle_id: 'r1', target_handle_id: 'l1' }]}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-edge-hit')).toBeTruthy()
    })

    const edgeHit = container.querySelector('.flow-ws-edge-hit')
    fireEvent.doubleClick(edgeHit, { clientX: 280, clientY: 240 })

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      expect(payload?.edges?.[0]?.control_points).toHaveLength(1)
      expect(payload?.edges?.[0]?.control_point_style).toBe('hard')
      expect(container.querySelectorAll('.flow-ws-edge-control')).toHaveLength(1)
    })

    const bendStyleField = screen.getByText('bend style').closest('label')
    const bendStyleSelect = bendStyleField?.querySelector('select')
    expect(bendStyleSelect).toBeTruthy()
    fireEvent.change(bendStyleSelect, { target: { value: 'curved' } })

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      expect(payload?.edges?.[0]?.control_point_style).toBe('curved')
    })

    const firstPoint = lastGraphPayload(onGraphChange)?.edges?.[0]?.control_points?.[0]
    const controlHandle = container.querySelector('.flow-ws-edge-control-hit')
    fireEvent.pointerDown(controlHandle, { button: 0, clientX: 280, clientY: 240 })
    fireEvent.pointerMove(window, { clientX: 360, clientY: 300 })
    fireEvent.pointerUp(window, { clientX: 360, clientY: 300 })

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      expect(payload?.edges?.[0]?.control_points).toHaveLength(1)
      expect(payload?.edges?.[0]?.control_points?.[0]).not.toEqual(firstPoint)
    })
  })

  test('shows connector save and delete actions in header and omits bend point count', async () => {
    const onGraphChange = vi.fn()
    const onSaveGraph = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'task', x: 520, y: 220, config: { task_prompt: 'run' } },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 2, source_handle_id: 'r1', target_handle_id: 'l1' }]}
        onGraphChange={onGraphChange}
        onSaveGraph={onSaveGraph}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-edge-hit')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-edge-hit'))

    expect(screen.getByLabelText('Save graph')).toBeTruthy()
    expect(screen.getByLabelText('Delete connector')).toBeTruthy()
    expect(screen.getByRole('option', { name: 'Trigger + Context' })).toBeTruthy()
    expect(screen.getByRole('option', { name: 'Context Only' })).toBeTruthy()
    expect(screen.queryByText('condition key')).toBeNull()
    expect(screen.queryByText('connector id')).toBeNull()
    expect(screen.queryByText('bend points')).toBeNull()

    fireEvent.click(screen.getByLabelText('Save graph'))
    expect(onSaveGraph).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByLabelText('Delete connector'))
    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      expect(payload?.edges).toHaveLength(0)
    })
  })

  test('zooms the graph on plain mouse wheel over viewport', async () => {
    const { container } = render(<FlowchartWorkspaceEditor />)
    const viewport = container.querySelector('.flow-ws-viewport')
    expect(viewport).toBeTruthy()
    expect(container.querySelector('.flow-ws-zoom-label')?.textContent).toBe('100%')

    fireEvent.wheel(viewport, { deltaY: -120, clientX: 300, clientY: 200 })

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-zoom-label')?.textContent).toBe('110%')
    })
  })

  test('prevents default wheel scrolling while applying viewport zoom', () => {
    const { container } = render(<FlowchartWorkspaceEditor />)
    const viewport = container.querySelector('.flow-ws-viewport')
    expect(viewport).toBeTruthy()

    const wheelEvent = new WheelEvent('wheel', {
      bubbles: true,
      cancelable: true,
      deltaY: -120,
      clientX: 300,
      clientY: 200,
    })
    let dispatchResult = true
    act(() => {
      dispatchResult = viewport.dispatchEvent(wheelEvent)
    })

    expect(dispatchResult).toBe(false)
    expect(wheelEvent.defaultPrevented).toBe(true)
  })

  test('applies consecutive wheel zoom events without dropping steps', async () => {
    const { container } = render(<FlowchartWorkspaceEditor />)
    const viewport = container.querySelector('.flow-ws-viewport')
    expect(viewport).toBeTruthy()
    expect(container.querySelector('.flow-ws-zoom-label')?.textContent).toBe('100%')

    act(() => {
      fireEvent.wheel(viewport, { deltaY: -120, clientX: 300, clientY: 200 })
      fireEvent.wheel(viewport, { deltaY: -120, clientX: 300, clientY: 200 })
    })

    await waitFor(() => {
      const zoomLabel = String(container.querySelector('.flow-ws-zoom-label')?.textContent || '0').replace('%', '')
      const zoomPercent = Number.parseInt(zoomLabel, 10)
      expect(Number.isNaN(zoomPercent)).toBe(false)
      expect(zoomPercent).toBeGreaterThanOrEqual(120)
    })
  })

  test('shows task validation hint when task node has no prompt', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'task', x: 500, y: 220, config: { task_prompt: '' } },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 2, source_handle_id: 'r1', target_handle_id: 'l1' }]}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    expect(screen.getByText('Task nodes require a non-empty task prompt before save/validate.')).toBeTruthy()
  })

  test('sets and clears task agent binding from inspector dropdown', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'task', x: 500, y: 220, config: { task_prompt: 'Run task' } },
        ]}
        initialEdges={[]}
        catalog={{
          agents: [
            { id: 3, name: 'Agent Three' },
            { id: 7, name: 'Agent Seven' },
          ],
          mcp_servers: [
            { id: 11, name: 'LLMCTL MCP', server_key: 'llmctl-mcp' },
          ],
        }}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))

    const agentField = screen.getByText('agent').closest('label')
    expect(agentField).toBeTruthy()
    const agentSelect = agentField.querySelector('select')
    expect(agentSelect).toBeTruthy()
    const llmctlMcpCheckbox = screen.getByLabelText(/LLMCTL MCP/)
    expect(llmctlMcpCheckbox).toBeChecked()
    expect(llmctlMcpCheckbox).toBeDisabled()

    fireEvent.change(agentSelect, { target: { value: '7' } })
    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const taskNode = payload?.nodes?.find((node) => node.id === 2)
      expect(taskNode?.config?.agent_id).toBe(7)
      expect(taskNode?.mcp_server_ids).toEqual([11])
    })

    fireEvent.change(agentSelect, { target: { value: '' } })
    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const taskNode = payload?.nodes?.find((node) => node.id === 2)
      expect(taskNode?.config?.agent_id).toBeUndefined()
      expect(taskNode?.mcp_server_ids).toEqual([11])
    })
  })

  test('shows runtime binding controls for decision nodes and hides them for start/end', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'decision', x: 500, y: 220, config: {} },
          { id: 3, node_type: 'end', x: 840, y: 220 },
        ]}
        initialEdges={[]}
        catalog={{
          agents: [
            { id: 4, name: 'Agent Four' },
            { id: 9, name: 'Agent Nine' },
          ],
          mcp_servers: [
            { id: 11, name: 'LLMCTL MCP', server_key: 'llmctl-mcp' },
            { id: 15, name: 'Diagnostics MCP', server_key: 'diag-mcp' },
          ],
        }}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:1"]'))
    expect(screen.queryByText('agent')).toBeFalsy()
    expect(screen.queryByText('MCP servers')).toBeFalsy()

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:3"]'))
    expect(screen.queryByText('agent')).toBeFalsy()
    expect(screen.queryByText('MCP servers')).toBeFalsy()

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    expect(screen.getByText('agent')).toBeTruthy()
    expect(screen.getByText('MCP servers')).toBeTruthy()
    const llmctlMcpCheckbox = screen.getByLabelText(/LLMCTL MCP/)
    expect(llmctlMcpCheckbox).toBeChecked()
    expect(llmctlMcpCheckbox).toBeDisabled()

    const agentField = screen.getByText('agent').closest('label')
    const agentSelect = agentField?.querySelector('select')
    expect(agentSelect).toBeTruthy()
    fireEvent.change(agentSelect, { target: { value: '9' } })

    fireEvent.click(screen.getByLabelText(/Diagnostics MCP/))

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const decisionNode = payload?.nodes?.find((node) => node.id === 2)
      expect(decisionNode?.config?.agent_id).toBe(9)
      expect(decisionNode?.mcp_server_ids).toEqual([11, 15])
    })
  })

  test('highlights running nodes when runtime reports active ids', async () => {
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'task', x: 500, y: 220 },
        ]}
        initialEdges={[]}
        runningNodeIds={['2']}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"].is-running')).toBeTruthy()
    })
    expect(container.querySelector('.flow-ws-node[data-node-token="id:1"].is-running')).toBeFalsy()
  })

  test('keeps selected node selected when applying saved graph response', async () => {
    const onGraphChange = vi.fn()
    const editorRef = createRef()
    const { container } = render(
      <FlowchartWorkspaceEditor
        ref={editorRef}
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200, title: 'Start' },
          { client_id: 41, node_type: 'task', x: 500, y: 220, title: 'Draft Task' },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 41, source_handle_id: 'r1', target_handle_id: 'l1' }]}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="client:41"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="client:41"]'))
    expect(container.querySelector('.flow-ws-node[data-node-token="client:41"].is-selected')).toBeTruthy()

    let applied = false
    act(() => {
      applied = editorRef.current.applyServerGraph(
        [
          { id: 1, node_type: 'start', x: 200, y: 200, title: 'Start' },
          { id: 7, node_type: 'task', x: 500, y: 220, title: 'Draft Task' },
        ],
        [{ id: 99, source_node_id: 1, target_node_id: 7, source_handle_id: 'r1', target_handle_id: 'l1' }],
      )
    })
    expect(applied).toBe(true)

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:7"].is-selected')).toBeTruthy()
    })
  })

  test('auto-manages decision conditions from solid outgoing connectors', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 120, y: 120, title: 'Start' },
          {
            id: 2,
            node_type: 'decision',
            x: 320,
            y: 120,
            title: 'Decision',
            config: {
              decision_conditions: [{ connector_id: 'stale_connector', condition_text: 'stale' }],
            },
          },
          { id: 3, node_type: 'task', x: 560, y: 80, title: 'Task' },
          { id: 4, node_type: 'task', x: 560, y: 200, title: 'Task' },
        ]}
        initialEdges={[
          {
            source_node_id: 1,
            target_node_id: 2,
            source_handle_id: 'r1',
            target_handle_id: 'l1',
            edge_mode: 'solid',
          },
          {
            source_node_id: 2,
            target_node_id: 3,
            source_handle_id: 'r1',
            target_handle_id: 'l1',
            edge_mode: 'solid',
            condition_key: 'left_connector',
          },
          {
            source_node_id: 2,
            target_node_id: 4,
            source_handle_id: 'b3',
            target_handle_id: 'l1',
            edge_mode: 'solid',
            condition_key: 'right_connector',
          },
        ]}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const decisionNode = payload?.nodes?.find((node) => node.node_type === 'decision')
      expect(decisionNode?.config?.decision_conditions).toEqual([
        { connector_id: 'left_connector', condition_text: '' },
        { connector_id: 'right_connector', condition_text: '' },
      ])
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    const firstConditionInput = screen.getByLabelText('left_connector -> Task')
    fireEvent.change(firstConditionInput, { target: { value: 'route left when approved' } })

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const decisionNode = payload?.nodes?.find((node) => node.node_type === 'decision')
      expect(decisionNode?.config?.decision_conditions).toEqual([
        { connector_id: 'left_connector', condition_text: 'route left when approved' },
        { connector_id: 'right_connector', condition_text: '' },
      ])
    })
  })

  test('renders milestone specialized controls and emits milestone action config', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'milestone', x: 520, y: 220, ref_id: 9, config: {} },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 2 }]}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    expect(screen.getByText('Create/Update milestone')).toBeTruthy()
    expect(screen.getByText('Mark milestone complete')).toBeTruthy()
    expect(screen.getByText('optional additive prompt')).toBeTruthy()
    expect(screen.queryByText(/^ref$/i)).toBeFalsy()
    expect(screen.queryByText('model')).toBeFalsy()
    expect(screen.getByText('agent')).toBeTruthy()

    const actionField = screen.getByText('action').closest('label')
    const actionSelect = actionField?.querySelector('select')
    expect(actionSelect).toBeTruthy()
    expect(actionSelect).toHaveAttribute('required')
    fireEvent.change(actionSelect, { target: { value: 'mark_complete' } })

    const additivePromptField = screen.getByText('optional additive prompt').closest('label')
    const additivePromptInput = additivePromptField?.querySelector('textarea')
    expect(additivePromptInput).toBeTruthy()
    fireEvent.change(additivePromptInput, { target: { value: 'close out release scope' } })

    const retentionField = screen.getByText('artifact retention').closest('label')
    const retentionSelect = retentionField?.querySelector('select')
    expect(retentionSelect).toBeTruthy()
    fireEvent.change(retentionSelect, { target: { value: 'max_count' } })

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const milestoneNode = payload?.nodes?.find((node) => node.node_type === 'milestone')
      expect(milestoneNode).toBeTruthy()
      expect(milestoneNode?.config?.action).toBe('mark_complete')
      expect(milestoneNode?.config?.additive_prompt).toBe('close out release scope')
      expect(milestoneNode?.config?.retention_mode).toBe('max_count')
    })
  })

  test('renders plan specialized controls and emits complete-plan-item config', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'plan', x: 520, y: 220, ref_id: 9, config: {} },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 2 }]}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    expect(screen.getByText('Create or update plan')).toBeTruthy()
    expect(screen.getByText('Complete plan item')).toBeTruthy()
    expect(screen.getByText('optional additive prompt')).toBeTruthy()
    expect(screen.queryByText(/^ref$/i)).toBeFalsy()
    expect(screen.queryByText('model')).toBeFalsy()
    expect(screen.getByText('agent')).toBeTruthy()

    const actionField = screen.getByText('action').closest('label')
    const actionSelect = actionField?.querySelector('select')
    expect(actionSelect).toBeTruthy()
    expect(actionSelect).toHaveAttribute('required')
    fireEvent.change(actionSelect, { target: { value: 'complete_plan_item' } })
    expect(screen.getByText('Complete plan item requires plan item id, stage+task keys, or completion source path.')).toBeTruthy()

    const additivePromptField = screen.getByText('optional additive prompt').closest('label')
    const additivePromptInput = additivePromptField?.querySelector('textarea')
    expect(additivePromptInput).toBeTruthy()
    fireEvent.change(additivePromptInput, { target: { value: 'mark only validated item' } })

    const planItemIdField = screen.getByText('plan item id (preferred)').closest('label')
    const planItemIdInput = planItemIdField?.querySelector('input')
    expect(planItemIdInput).toBeTruthy()
    fireEvent.change(planItemIdInput, { target: { value: '17' } })

    const retentionField = screen.getByText('artifact retention').closest('label')
    const retentionSelect = retentionField?.querySelector('select')
    expect(retentionSelect).toBeTruthy()
    fireEvent.change(retentionSelect, { target: { value: 'max_count' } })

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const planNode = payload?.nodes?.find((node) => node.node_type === 'plan')
      expect(planNode).toBeTruthy()
      expect(planNode?.config?.action).toBe('complete_plan_item')
      expect(planNode?.config?.additive_prompt).toBe('mark only validated item')
      expect(planNode?.config?.plan_item_id).toBe(17)
      expect(planNode?.config?.retention_mode).toBe('max_count')
    })
  })

  test('renders memory specialized controls, auto-locks llmctl mcp, and emits memory config', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'memory', x: 520, y: 220, ref_id: 9, config: {} },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 2 }]}
        catalog={{
          agents: [
            { id: 5, name: 'Agent Five' },
          ],
          mcp_servers: [
            { id: 3, name: 'Custom MCP', server_key: 'custom-mcp' },
            { id: 11, name: 'LLMCTL MCP', server_key: 'llmctl-mcp' },
          ],
        }}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    expect(screen.getByText('Add memory')).toBeTruthy()
    expect(screen.getByText('Retrieve memory')).toBeTruthy()
    expect(screen.getByText('LLM-guided')).toBeTruthy()
    expect(screen.getByText('Deterministic')).toBeTruthy()
    expect(screen.getByText('store mode')).toBeTruthy()
    expect(screen.getByText('Additive')).toBeTruthy()
    expect(screen.getByText('Replace')).toBeTruthy()
    expect(screen.getByText('optional additive prompt')).toBeTruthy()
    expect(screen.getByText('Failure')).toBeTruthy()
    expect(screen.getByText('retry count')).toBeTruthy()
    expect(screen.getByText('fallback enabled')).toBeTruthy()
    expect(screen.queryByText(/^ref$/i)).toBeFalsy()
    expect(screen.getByText('artifact retention')).toBeTruthy()
    expect(screen.getByLabelText(/LLMCTL MCP/)).toBeChecked()
    expect(screen.getByLabelText(/LLMCTL MCP/)).toBeDisabled()
    expect(screen.queryByText('model')).toBeFalsy()
    expect(screen.getByText('agent')).toBeTruthy()
    expect(screen.getByText('MCP servers')).toBeTruthy()

    const actionField = screen.getByText('action').closest('label')
    const actionSelect = actionField?.querySelector('select')
    expect(actionSelect).toBeTruthy()
    expect(actionSelect).toHaveAttribute('required')
    fireEvent.change(actionSelect, { target: { value: 'retrieve' } })

    const modeField = screen.getByText('mode').closest('label')
    const modeSelect = modeField?.querySelector('select')
    expect(modeSelect).toBeTruthy()
    fireEvent.change(modeSelect, { target: { value: 'deterministic' } })

    const storeModeField = screen.getByText('store mode').closest('label')
    const storeModeSelect = storeModeField?.querySelector('select')
    expect(storeModeSelect).toBeTruthy()
    fireEvent.change(storeModeSelect, { target: { value: 'append' } })

    const additivePromptField = screen.getByText('optional additive prompt').closest('label')
    const additivePromptInput = additivePromptField?.querySelector('textarea')
    expect(additivePromptInput).toBeTruthy()
    fireEvent.change(additivePromptInput, { target: { value: 'find deployment readiness notes' } })

    const retentionField = screen.getByText('artifact retention').closest('label')
    const retentionSelect = retentionField?.querySelector('select')
    expect(retentionSelect).toBeTruthy()
    fireEvent.change(retentionSelect, { target: { value: 'max_count' } })

    const retryCountField = screen.getByText('retry count').closest('label')
    const retryCountInput = retryCountField?.querySelector('input')
    expect(retryCountInput).toBeTruthy()
    fireEvent.change(retryCountInput, { target: { value: '3' } })

    const fallbackField = screen.getByText('fallback enabled').closest('label')
    const fallbackSelect = fallbackField?.querySelector('select')
    expect(fallbackSelect).toBeTruthy()
    fireEvent.change(fallbackSelect, { target: { value: 'false' } })

    const agentField = screen.getByText('agent').closest('label')
    const agentSelect = agentField?.querySelector('select')
    expect(agentSelect).toBeTruthy()
    fireEvent.change(agentSelect, { target: { value: '5' } })

    fireEvent.click(screen.getByLabelText(/Custom MCP/))

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const memoryNode = payload?.nodes?.find((node) => node.node_type === 'memory')
      expect(memoryNode).toBeTruthy()
      expect(memoryNode?.config?.action).toBe('retrieve')
      expect(memoryNode?.config?.mode).toBe('deterministic')
      expect(memoryNode?.config?.store_mode).toBe('append')
      expect(memoryNode?.config?.additive_prompt).toBe('find deployment readiness notes')
      expect(memoryNode?.config?.retry_count).toBe(3)
      expect(memoryNode?.config?.fallback_enabled).toBe(false)
      expect(memoryNode?.config?.retention_mode).toBe('max_count')
      expect(memoryNode?.config?.agent_id).toBe(5)
      expect(memoryNode?.mcp_server_ids).toEqual([11, 3])
    })
  })

  test('renders rag controls and emits rag config updates', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'rag', x: 520, y: 220, config: {} },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 2 }]}
        catalog={{
          rag_collections: [
            { id: 'docs', name: 'Docs', status: 'ready' },
            { id: 'runbooks', name: 'Runbooks', status: 'ready' },
          ],
          mcp_servers: [
            { id: 11, name: 'LLMCTL MCP', server_key: 'llmctl-mcp' },
          ],
        }}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    expect(screen.getByText('rag mode')).toBeTruthy()
    expect(screen.getByText('collections')).toBeTruthy()
    expect(screen.getByText('query prompt')).toBeTruthy()
    expect(screen.getByText('MCP servers')).toBeTruthy()
    const ragMcpCheckbox = screen.getByLabelText(/LLMCTL MCP/)
    expect(ragMcpCheckbox).not.toBeChecked()
    expect(ragMcpCheckbox).toBeDisabled()
    expect(screen.getByText('RAG nodes do not support MCP servers.')).toBeTruthy()

    const modeField = screen.getByText('rag mode').closest('label')
    const modeSelect = modeField?.querySelector('select')
    expect(modeSelect).toBeTruthy()
    fireEvent.change(modeSelect, { target: { value: 'delta_index' } })

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const ragNode = payload?.nodes?.find((node) => node.node_type === 'rag')
      expect(ragNode?.config?.mode).toBe('delta_index')
      expect(ragNode?.mcp_server_ids).toEqual([])
    })
    expect(screen.queryByText('query prompt')).toBeFalsy()

    const docsCollectionCheckbox = screen.getByLabelText(/Docs \(ready\)/)
    expect(docsCollectionCheckbox).toBeTruthy()
    fireEvent.click(docsCollectionCheckbox)

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const ragNode = payload?.nodes?.find((node) => node.node_type === 'rag')
      expect(ragNode?.config?.collections).toEqual(['docs'])
      expect(ragNode?.mcp_server_ids).toEqual([])
    })
  })

  test('renders collections controls for task nodes and emits collection updates', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'task', x: 520, y: 220, config: { task_prompt: 'Use docs' } },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 2 }]}
        catalog={{
          rag_collections: [
            { id: 'docs', name: 'Docs', status: 'ready' },
            { id: 'runbooks', name: 'Runbooks', status: 'ready' },
          ],
        }}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    expect(screen.getByText('collections')).toBeTruthy()

    const docsCollectionCheckbox = screen.getByLabelText(/Docs \(ready\)/)
    expect(docsCollectionCheckbox).toBeTruthy()
    fireEvent.click(docsCollectionCheckbox)

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const taskNode = payload?.nodes?.find((node) => node.node_type === 'task')
      expect(taskNode?.config?.collections).toEqual(['docs'])
    })
  })

  test('preserves selected collections when changing node type from rag to task', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          {
            id: 2,
            node_type: 'rag',
            x: 520,
            y: 220,
            config: { mode: 'query', collections: ['docs'], question_prompt: 'query docs' },
          },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 2 }]}
        catalog={{
          rag_collections: [
            { id: 'docs', name: 'Docs', status: 'ready' },
          ],
        }}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    const typeField = screen.getByText('type').closest('label')
    const typeSelect = typeField?.querySelector('select')
    expect(typeSelect).toBeTruthy()
    fireEvent.change(typeSelect, { target: { value: 'task' } })

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const convertedNode = payload?.nodes?.find((node) => node.id === 2)
      expect(convertedNode?.node_type).toBe('task')
      expect(convertedNode?.config?.collections).toEqual(['docs'])
    })
  })

  test('filters rag index-mode model options to embedding models only', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          {
            id: 2,
            node_type: 'rag',
            x: 520,
            y: 220,
            model_id: 2,
            config: { mode: 'fresh_index', collections: ['docs'] },
          },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 2 }]}
        catalog={{
          models: [
            { id: 1, name: 'Embedding Model', provider: 'codex', model_name: 'text-embedding-3-small' },
            { id: 2, name: 'Chat Model', provider: 'codex', model_name: 'gpt-5' },
            { id: 3, name: 'Gemini Chat', provider: 'gemini', model_name: 'gemini-2.5-pro' },
            { id: 4, name: 'Flagged Embedding', provider: 'codex', model_name: 'gpt-5', is_embedding: true },
          ],
          rag_collections: [
            { id: 'docs', name: 'Docs', status: 'ready' },
          ],
          mcp_servers: [
            { id: 11, name: 'LLMCTL MCP', server_key: 'llmctl-mcp' },
          ],
        }}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    expect(screen.getByText('Index modes require an embedding model selection.')).toBeTruthy()

    const modelField = screen.getByText('model').closest('label')
    const modelSelect = modelField?.querySelector('select')
    expect(modelSelect).toBeTruthy()
    const modelOptionTexts = Array.from(modelSelect.options).map((item) => String(item.textContent || '').trim())
    expect(modelOptionTexts).toContain('Embedding Model')
    expect(modelOptionTexts).toContain('Flagged Embedding')
    expect(modelOptionTexts).not.toContain('Chat Model')
    expect(modelOptionTexts).not.toContain('Gemini Chat')
  })

  test('renders routing summary chips, updates routing config, and blocks invalid saves', async () => {
    const onGraphChange = vi.fn()
    const onNotice = vi.fn()
    const onSaveGraph = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 120, y: 120 },
          { id: 2, node_type: 'task', x: 260, y: 40, config: { task_prompt: 'A' } },
          {
            id: 3,
            node_type: 'decision',
            x: 260,
            y: 200,
            config: {
              fan_in_mode: 'custom',
              fan_in_custom_count: 3,
              no_match_policy: 'fallback',
              fallback_condition_key: 'missing_connector',
            },
          },
          { id: 4, node_type: 'task', x: 520, y: 200, config: { task_prompt: 'B' } },
        ]}
        initialEdges={[
          { source_node_id: 1, target_node_id: 2, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid' },
          { source_node_id: 2, target_node_id: 3, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid' },
          { source_node_id: 3, target_node_id: 4, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid', condition_key: 'approve' },
        ]}
        onGraphChange={onGraphChange}
        onNotice={onNotice}
        onSaveGraph={onSaveGraph}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:3"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:3"]'))
    expect(screen.getByText('Routing')).toBeTruthy()
    expect(document.getElementById('flow-ws-routing-details')?.open).toBe(false)
    expect(screen.getByText('custom 3')).toBeTruthy()
    expect(screen.getByText('fallback missing_connector')).toBeTruthy()
    expect(screen.getByText('invalid 2')).toBeTruthy()

    fireEvent.click(screen.getByLabelText('Save graph'))

    await waitFor(() => {
      expect(onSaveGraph).not.toHaveBeenCalled()
      expect(onNotice).toHaveBeenCalled()
      expect(document.getElementById('flow-ws-routing-details')?.open).toBe(true)
    })
    expect(screen.getByText('Custom N must be <= solid incoming connector count (1).')).toBeTruthy()
    expect(screen.getByText('Fallback connector must match a solid outgoing connector.')).toBeTruthy()

    const fallbackField = screen.getByText('fallback connector').closest('label')
    const fallbackSelect = fallbackField?.querySelector('select')
    expect(fallbackSelect).toBeTruthy()
    fireEvent.change(fallbackSelect, { target: { value: 'approve' } })

    const fanInModeField = screen.getByText('fan-in mode').closest('label')
    const fanInModeSelect = fanInModeField?.querySelector('select')
    expect(fanInModeSelect).toBeTruthy()
    fireEvent.change(fanInModeSelect, { target: { value: 'any' } })

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const decisionNode = payload?.nodes?.find((node) => node.id === 3)
      expect(decisionNode?.config?.fan_in_mode).toBe('any')
      expect(decisionNode?.config?.fan_in_custom_count).toBeUndefined()
      expect(decisionNode?.config?.no_match_policy).toBe('fallback')
      expect(decisionNode?.config?.fallback_condition_key).toBe('approve')
    })

    fireEvent.click(screen.getByLabelText('Save graph'))
    await waitFor(() => {
      expect(onSaveGraph).toHaveBeenCalledTimes(1)
    })
  })

  test('keeps tracing controls runtime-only by omitting routing tracing toggles in the inspector', async () => {
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 120, y: 120 },
          { id: 2, node_type: 'decision', x: 300, y: 120, config: {} },
          { id: 3, node_type: 'task', x: 520, y: 120, config: { task_prompt: 'Run branch' } },
        ]}
        initialEdges={[
          { source_node_id: 1, target_node_id: 2, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid' },
          { source_node_id: 2, target_node_id: 3, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid', condition_key: 'approve' },
        ]}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    expect(screen.getByText('Routing')).toBeTruthy()
    fireEvent.click(screen.getByText('Routing'))
    expect(screen.queryByText(/connector tracing/i)).toBeNull()
    expect(screen.queryByText(/verbosity/i)).toBeNull()
    expect(screen.queryByLabelText(/tracing/i)).toBeNull()
  })

  test('auto-clamps custom fan-in and emits a warning when solid upstream connectors shrink', async () => {
    const onGraphChange = vi.fn()
    const onNotice = vi.fn()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    try {
      const { container } = render(
        <FlowchartWorkspaceEditor
          initialNodes={[
            { id: 1, node_type: 'start', x: 120, y: 120 },
            { id: 2, node_type: 'task', x: 280, y: 40, config: { task_prompt: 'Route A' } },
            { id: 3, node_type: 'task', x: 280, y: 220, config: { task_prompt: 'Route B' } },
            { id: 4, node_type: 'decision', x: 560, y: 120, config: { fan_in_mode: 'custom', fan_in_custom_count: 2 } },
          ]}
          initialEdges={[
            { source_node_id: 1, target_node_id: 2, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid' },
            { source_node_id: 1, target_node_id: 3, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid' },
            { source_node_id: 2, target_node_id: 4, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid' },
            { source_node_id: 3, target_node_id: 4, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid' },
          ]}
          onGraphChange={onGraphChange}
          onNotice={onNotice}
        />,
      )

      await waitFor(() => {
        expect(container.querySelector('.flow-ws-node[data-node-token="id:3"]')).toBeTruthy()
      })

      fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:3"]'))
      fireEvent.click(screen.getByLabelText('Delete node'))

      await waitFor(() => {
        const payload = lastGraphPayload(onGraphChange)
        const decisionNode = payload?.nodes?.find((node) => node.id === 4)
        expect(decisionNode?.config?.fan_in_mode).toBe('custom')
        expect(decisionNode?.config?.fan_in_custom_count).toBe(1)
      })
      await waitFor(() => {
        expect(onNotice).toHaveBeenCalledWith(expect.stringContaining('auto-clamped'))
      })
    } finally {
      confirmSpy.mockRestore()
    }
  })

  test('keeps routing inspector single-select and avoids bulk-edit fan-in updates', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 120, y: 120 },
          { id: 2, node_type: 'task', x: 320, y: 40, config: { task_prompt: 'Task A', fan_in_mode: 'custom', fan_in_custom_count: 1 } },
          { id: 3, node_type: 'task', x: 320, y: 220, config: { task_prompt: 'Task B', fan_in_mode: 'custom', fan_in_custom_count: 1 } },
        ]}
        initialEdges={[
          { source_node_id: 1, target_node_id: 2, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid' },
          { source_node_id: 1, target_node_id: 3, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid' },
        ]}
        onGraphChange={onGraphChange}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
      expect(container.querySelector('.flow-ws-node[data-node-token="id:3"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:3"]'), { shiftKey: true })
    expect(container.querySelectorAll('.flow-ws-node.is-selected')).toHaveLength(1)

    fireEvent.click(screen.getByText('Routing'))
    const fanInModeField = screen.getByText('fan-in mode').closest('label')
    const fanInModeSelect = fanInModeField?.querySelector('select')
    expect(fanInModeSelect).toBeTruthy()
    fireEvent.change(fanInModeSelect, { target: { value: 'any' } })

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const taskA = payload?.nodes?.find((node) => node.id === 2)
      const taskB = payload?.nodes?.find((node) => node.id === 3)
      expect(taskA?.config?.fan_in_mode).toBe('custom')
      expect(taskA?.config?.fan_in_custom_count).toBe(1)
      expect(taskB?.config?.fan_in_mode).toBe('any')
      expect(taskB?.config?.fan_in_custom_count).toBeUndefined()
    })
  })

  test('preserves invalid routing draft edits across collapse and reopen', async () => {
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 120, y: 120 },
          { id: 2, node_type: 'task', x: 260, y: 40, config: { task_prompt: 'A' } },
          {
            id: 3,
            node_type: 'decision',
            x: 260,
            y: 200,
            config: {
              fan_in_mode: 'custom',
              fan_in_custom_count: 3,
              no_match_policy: 'fallback',
              fallback_condition_key: 'missing_connector',
            },
          },
          { id: 4, node_type: 'task', x: 520, y: 200, config: { task_prompt: 'B' } },
        ]}
        initialEdges={[
          { source_node_id: 1, target_node_id: 2, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid' },
          { source_node_id: 2, target_node_id: 3, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid' },
          { source_node_id: 3, target_node_id: 4, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid', condition_key: 'approve' },
        ]}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:3"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:3"]'))
    const routingDetails = document.getElementById('flow-ws-routing-details')
    expect(routingDetails).toBeTruthy()
    if (routingDetails?.open) {
      fireEvent.click(screen.getByText('Routing'))
      await waitFor(() => {
        expect(routingDetails?.open).toBe(false)
      })
    }

    fireEvent.click(screen.getByText('Routing'))
    await waitFor(() => {
      expect(routingDetails?.open).toBe(true)
    })

    const customInput = routingDetails?.querySelector('input[type="number"]')
    expect(customInput).toBeTruthy()
    fireEvent.change(customInput, { target: { value: '2' } })

    await waitFor(() => {
      expect(screen.getByText('custom 2')).toBeTruthy()
    })

    fireEvent.click(screen.getByText('Routing'))
    await waitFor(() => {
      expect(routingDetails?.open).toBe(false)
    })

    fireEvent.click(screen.getByText('Routing'))
    await waitFor(() => {
      expect(routingDetails?.open).toBe(true)
    })

    const reopenedInput = routingDetails?.querySelector('input[type="number"]')
    expect(reopenedInput).toHaveValue(2)
    expect(screen.getByText('fallback missing_connector')).toBeTruthy()

    fireEvent.click(screen.getByText('Routing'))
    await waitFor(() => {
      expect(routingDetails?.open).toBe(false)
    })
  })

  test('renders routing controls only for node types that support routing', async () => {
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 120, y: 120 },
          { id: 2, node_type: 'task', x: 340, y: 120, config: { task_prompt: 'Run task' } },
        ]}
        initialEdges={[]}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-node[data-node-token="id:1"]')).toBeTruthy()
      expect(container.querySelector('.flow-ws-node[data-node-token="id:2"]')).toBeTruthy()
    })

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:1"]'))
    expect(screen.queryByText('Routing')).toBeNull()

    fireEvent.click(container.querySelector('.flow-ws-node[data-node-token="id:2"]'))
    expect(screen.getByText('Routing')).toBeTruthy()
  })

  test('renders fallback badge on the configured decision connector edge', async () => {
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 120, y: 120 },
          {
            id: 2,
            node_type: 'decision',
            x: 300,
            y: 120,
            config: { no_match_policy: 'fallback', fallback_condition_key: 'reject' },
          },
          { id: 3, node_type: 'task', x: 560, y: 120, config: { task_prompt: 'Run branch' } },
        ]}
        initialEdges={[
          { source_node_id: 1, target_node_id: 2, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid' },
          { source_node_id: 2, target_node_id: 3, source_handle_id: 'r1', target_handle_id: 'l1', edge_mode: 'solid', condition_key: 'reject' },
        ]}
      />,
    )

    await waitFor(() => {
      expect(container.querySelector('.flow-ws-edge-fallback-badge')).toBeTruthy()
    })
    expect(screen.getByText('fallback')).toBeTruthy()
  })
})
