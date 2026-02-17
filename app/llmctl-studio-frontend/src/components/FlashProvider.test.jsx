import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { useFlash, useFlashState } from '../lib/flashMessages'
import FlashProvider from './FlashProvider'

function TriggerButton() {
  const flash = useFlash()
  return (
    <button type="button" onClick={() => flash.success('Saved changes.')}>
      Trigger
    </button>
  )
}

function ErrorStateButton() {
  const [, setActionError] = useFlashState('error')
  return (
    <button type="button" onClick={() => setActionError('Action failed.')}>
      Trigger Error
    </button>
  )
}

describe('FlashProvider', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  test('renders a pushed flash message and auto-dismisses it', () => {
    vi.useFakeTimers()

    render(
      <FlashProvider>
        <TriggerButton />
      </FlashProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Trigger' }))
    expect(screen.getByText('Saved changes.')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(4300)
    })

    expect(screen.queryByText('Saved changes.')).not.toBeInTheDocument()
  })

  test('publishes useFlashState error updates into the viewport', () => {
    render(
      <FlashProvider>
        <ErrorStateButton />
      </FlashProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Trigger Error' }))
    expect(screen.getByText('Action failed.')).toBeInTheDocument()
  })
})
