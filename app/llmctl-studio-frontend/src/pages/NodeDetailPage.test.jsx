import { describe, expect, test } from 'vitest'
import { nodeHistoryHref, stageLogEmptyMessage } from './NodeDetailPage'

describe('NodeDetailPage stage log empty state', () => {
  test('shows indexing wait message for rag indexing stage label', () => {
    expect(stageLogEmptyMessage({ label: 'RAG Indexing' }, 0)).toBe('Waiting for indexing logs...')
  })

  test('shows indexing wait message for rag delta indexing stage label', () => {
    expect(stageLogEmptyMessage({ label: 'RAG Delta Indexing' }, 0)).toBe('Waiting for indexing logs...')
  })

  test('falls back to generic empty stage message for non-indexing labels', () => {
    expect(stageLogEmptyMessage({ label: 'LLM Query' }, 0)).toBe('No logs yet.')
  })
})

describe('NodeDetailPage node history link', () => {
  test('uses flowchart node id when available', () => {
    expect(nodeHistoryHref({ flowchart_node_id: 17 })).toBe('/nodes?flowchart_node_id=17')
  })

  test('falls back to all nodes when flowchart node id is missing', () => {
    expect(nodeHistoryHref({})).toBe('/nodes')
  })
})
