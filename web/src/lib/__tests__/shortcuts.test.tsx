import { fireEvent, render, screen } from '@testing-library/react'
import { rowIndex, useShortcuts } from '@/lib/shortcuts'

describe('workspace shortcuts', () => {
  it('handles the palette chord, a navigation sequence and a shifted action', () => {
    const palette = vi.fn(), runs = vi.fn(), fresh = vi.fn(), process = vi.fn()
    function Harness() {
      useShortcuts({ palette, runs, fresh, process })
      return <input aria-label="Invoice search" />
    }
    render(<Harness />)
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    fireEvent.keyDown(window, { key: 'g' })
    fireEvent.keyDown(window, { key: 'r' })
    fireEvent.keyDown(window, { key: 'P', shiftKey: true })
    expect(palette).toHaveBeenCalledTimes(1)
    expect(runs).toHaveBeenCalledTimes(1)
    expect(fresh).toHaveBeenCalledTimes(1)
    expect(process).not.toHaveBeenCalled()
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'p' })
    expect(process).not.toHaveBeenCalled()
  })

  it('keeps selection within the current rows', () => {
    expect(rowIndex(-1, 4, 'next')).toBe(0)
    expect(rowIndex(-1, 4, 'previous')).toBe(3)
    expect(rowIndex(3, 4, 'next')).toBe(3)
    expect(rowIndex(0, 0, 'next')).toBe(-1)
  })
})
