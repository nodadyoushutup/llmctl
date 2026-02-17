import { render, waitFor } from '@testing-library/react'
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
    expect(startNode).toMatchObject({ x: 2046, y: 1246 })
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
    expect(startNode).toMatchObject({ x: 2046, y: 1246 })
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
})
