import { describe, expect, test } from 'vitest'
import { routeCountMeta } from '../lib/flowchartRouting'

describe('FlowchartRunDetailPage route count summary', () => {
  test('counts matched connectors when available', () => {
    expect(routeCountMeta({ matched_connector_ids: ['approve', 'fallback', 'approve'] })).toEqual({
      routeCount: 2,
      reason: 'matched',
    })
  })

  test('falls back to route_key when matched connectors are absent', () => {
    expect(routeCountMeta({ route_key: 'next' })).toEqual({
      routeCount: 1,
      reason: 'route_key',
    })
  })

  test('reports no match when routing explicitly reports no_match', () => {
    expect(routeCountMeta({ no_match: true })).toEqual({
      routeCount: 0,
      reason: 'no_match',
    })
  })

  test('returns null when routing state does not include route signals', () => {
    expect(routeCountMeta({})).toBeNull()
  })
})
