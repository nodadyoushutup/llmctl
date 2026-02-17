import { describe, expect, it } from 'vitest'

import { buildParitySummary, parityChecklist } from './checklist'

describe('parity checklist', () => {
  it('keeps all tracked areas on native react status', () => {
    expect(parityChecklist.every((item) => item.status === 'migrated')).toBe(true)
  })

  it('reports zero remaining migration gaps', () => {
    const summary = buildParitySummary(parityChecklist)
    expect(summary.pending).toBe(0)
    expect(summary.migrated).toBe(summary.total)
  })
})
