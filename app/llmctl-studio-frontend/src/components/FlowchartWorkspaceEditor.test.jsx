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

  test('shows task validation hint when task node has no prompt', async () => {
    const onGraphChange = vi.fn()
    const { container } = render(
      <FlowchartWorkspaceEditor
        initialNodes={[
          { id: 1, node_type: 'start', x: 200, y: 200 },
          { id: 2, node_type: 'task', x: 500, y: 220, ref_id: null, config: { task_prompt: '' } },
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
})
