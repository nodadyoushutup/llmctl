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

    fireEvent.change(agentSelect, { target: { value: '7' } })
    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const taskNode = payload?.nodes?.find((node) => node.id === 2)
      expect(taskNode?.config?.agent_id).toBe(7)
    })

    fireEvent.change(agentSelect, { target: { value: '' } })
    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const taskNode = payload?.nodes?.find((node) => node.id === 2)
      expect(taskNode?.config?.agent_id).toBeUndefined()
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
    expect(screen.queryByText('model')).toBeFalsy()
    expect(screen.queryByText('agent')).toBeFalsy()

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
    expect(screen.queryByText('model')).toBeFalsy()
    expect(screen.queryByText('agent')).toBeFalsy()

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

  test('renders memory specialized controls, locks llmctl mcp, and emits memory config', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'memory', x: 520, y: 220, ref_id: 9, config: {} },
        ]}
        initialEdges={[{ source_node_id: 1, target_node_id: 2 }]}
        catalog={{
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
    expect(screen.getByText('optional additive prompt')).toBeTruthy()
    expect(screen.getByText('artifact retention')).toBeTruthy()
    expect(screen.getByLabelText('LLMCTL MCP (required)')).toBeChecked()
    expect(screen.getByLabelText('LLMCTL MCP (required)')).toBeDisabled()
    expect(screen.queryByText('model')).toBeFalsy()
    expect(screen.queryByText('agent')).toBeFalsy()

    const actionField = screen.getByText('action').closest('label')
    const actionSelect = actionField?.querySelector('select')
    expect(actionSelect).toBeTruthy()
    expect(actionSelect).toHaveAttribute('required')
    fireEvent.change(actionSelect, { target: { value: 'retrieve' } })

    const additivePromptField = screen.getByText('optional additive prompt').closest('label')
    const additivePromptInput = additivePromptField?.querySelector('textarea')
    expect(additivePromptInput).toBeTruthy()
    fireEvent.change(additivePromptInput, { target: { value: 'find deployment readiness notes' } })

    const retentionField = screen.getByText('artifact retention').closest('label')
    const retentionSelect = retentionField?.querySelector('select')
    expect(retentionSelect).toBeTruthy()
    fireEvent.change(retentionSelect, { target: { value: 'max_count' } })

    await waitFor(() => {
      const payload = lastGraphPayload(onGraphChange)
      const memoryNode = payload?.nodes?.find((node) => node.node_type === 'memory')
      expect(memoryNode).toBeTruthy()
      expect(memoryNode?.config?.action).toBe('retrieve')
      expect(memoryNode?.config?.additive_prompt).toBe('find deployment readiness notes')
      expect(memoryNode?.config?.retention_mode).toBe('max_count')
      expect(memoryNode?.mcp_server_ids).toEqual([11])
    })
  })
})
