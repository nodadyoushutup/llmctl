import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, test } from 'vitest'
import PersistedDetails from './PersistedDetails'

describe('PersistedDetails', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  test('uses defaultOpen when no saved value exists', () => {
    const { container } = render(
      <PersistedDetails storageKey="unit-default-open" defaultOpen>
        <summary>Section</summary>
        <p>Body</p>
      </PersistedDetails>,
    )

    const details = container.querySelector('details')
    expect(details).not.toBeNull()
    expect(details?.open).toBe(true)
  })

  test('restores saved open state across remount', () => {
    const storageKey = 'unit-restore-open-state'
    const localStorageKey = `llmctl-ui-details:${storageKey}`

    const firstRender = render(
      <PersistedDetails storageKey={storageKey}>
        <summary>Section</summary>
        <p>Body</p>
      </PersistedDetails>,
    )

    const firstDetails = firstRender.container.querySelector('details')
    expect(firstDetails?.open).toBe(false)

    if (firstDetails) {
      firstDetails.open = true
      fireEvent(firstDetails, new Event('toggle'))
    }

    expect(window.localStorage.getItem(localStorageKey)).toBe('1')

    firstRender.unmount()

    const secondRender = render(
      <PersistedDetails storageKey={storageKey}>
        <summary>Section</summary>
        <p>Body</p>
      </PersistedDetails>,
    )

    const secondDetails = secondRender.container.querySelector('details')
    expect(secondDetails?.open).toBe(true)
    expect(screen.getByText('Body')).toBeInTheDocument()
  })
})
