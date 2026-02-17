import { describe, expect, it } from 'vitest'

import { shouldIgnoreRowClick } from './tableRowLink'

describe('tableRowLink', () => {
  it('returns false when target is missing', () => {
    expect(shouldIgnoreRowClick(null)).toBe(false)
  })

  it('returns false for non-interactive targets', () => {
    const row = document.createElement('tr')
    const cell = document.createElement('td')
    const content = document.createElement('div')
    row.appendChild(cell)
    cell.appendChild(content)

    expect(shouldIgnoreRowClick(content)).toBe(false)
  })

  it('returns true for interactive targets', () => {
    const row = document.createElement('tr')
    const cell = document.createElement('td')
    const button = document.createElement('button')
    const link = document.createElement('a')
    const input = document.createElement('input')
    const select = document.createElement('select')
    const textarea = document.createElement('textarea')
    const summary = document.createElement('summary')
    const details = document.createElement('details')
    row.appendChild(cell)
    cell.appendChild(button)
    cell.appendChild(link)
    cell.appendChild(input)
    cell.appendChild(select)
    cell.appendChild(textarea)
    cell.appendChild(summary)
    cell.appendChild(details)

    expect(shouldIgnoreRowClick(button)).toBe(true)
    expect(shouldIgnoreRowClick(link)).toBe(true)
    expect(shouldIgnoreRowClick(input)).toBe(true)
    expect(shouldIgnoreRowClick(select)).toBe(true)
    expect(shouldIgnoreRowClick(textarea)).toBe(true)
    expect(shouldIgnoreRowClick(summary)).toBe(true)
    expect(shouldIgnoreRowClick(details)).toBe(true)
  })

  it('returns true for nested elements inside interactive containers', () => {
    const row = document.createElement('tr')
    const cell = document.createElement('td')
    const label = document.createElement('label')
    const span = document.createElement('span')
    row.appendChild(cell)
    cell.appendChild(label)
    label.appendChild(span)

    expect(shouldIgnoreRowClick(span)).toBe(true)
  })
})
