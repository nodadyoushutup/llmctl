import { describe, expect, test } from 'vitest'
import { stageLogEmptyMessage } from './NodeDetailPage'

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
