import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import IntegerInput from './IntegerInput'

describe('IntegerInput', () => {
  it('keeps only integer digits when edited', () => {
    const onValueChange = vi.fn()
    render(<IntegerInput value="" onValueChange={onValueChange} aria-label="integer-field" />)

    fireEvent.change(screen.getByLabelText('integer-field'), {
      target: { value: '12ab34' },
    })

    expect(onValueChange).toHaveBeenCalledWith('1234')
  })

  it('supports negative integers when enabled', () => {
    const onValueChange = vi.fn()
    render(
      <IntegerInput
        value=""
        allowNegative
        onValueChange={onValueChange}
        aria-label="negative-integer-field"
      />,
    )

    fireEvent.change(screen.getByLabelText('negative-integer-field'), {
      target: { value: '-7x8' },
    })

    expect(onValueChange).toHaveBeenCalledWith('-78')
  })
})
