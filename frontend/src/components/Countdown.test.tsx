import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Countdown, formatDuration } from './Countdown'

/** Advance fake timers inside act so React flushes the tick's state update. */
async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('formatDuration', () => {
  it('formats mm:ss under an hour and h:mm:ss above it', () => {
    expect(formatDuration(0)).toBe('00:00')
    expect(formatDuration(65)).toBe('01:05')
    expect(formatDuration(599)).toBe('09:59')
    expect(formatDuration(3661)).toBe('1:01:01')
  })

  it('never renders a negative clock', () => {
    expect(formatDuration(-30)).toBe('00:00')
  })
})

describe('Countdown', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the server-provided remaining time', () => {
    render(<Countdown remainingSeconds={125} anchorKey="a" />)
    expect(screen.getByRole('timer')).toHaveTextContent('02:05')
  })

  it('ticks down from the server anchor', async () => {
    render(<Countdown remainingSeconds={125} anchorKey="a" />)
    await advance(3000)
    expect(screen.getByRole('timer')).toHaveTextContent('02:02')
  })

  it('re-anchors when the server reports a fresh value', async () => {
    const { rerender } = render(
      <Countdown remainingSeconds={125} anchorKey="a" />,
    )
    await advance(5000)
    expect(screen.getByRole('timer')).toHaveTextContent('02:00')

    // The server is authoritative: a refetch says more time is left than the
    // local tick believed, and the display follows the server.
    rerender(<Countdown remainingSeconds={300} anchorKey="b" />)
    expect(screen.getByRole('timer')).toHaveTextContent('05:00')
  })

  it('stops at zero and reports expiry once time is up', async () => {
    const onExpire = vi.fn()
    render(<Countdown remainingSeconds={2} anchorKey="a" onExpire={onExpire} />)
    await advance(5000)

    const timer = screen.getByRole('timer')
    expect(timer).toHaveTextContent('00:00')
    expect(timer).toHaveTextContent(/time is up/i)
    expect(onExpire).toHaveBeenCalled()
  })

  it('marks the final minute as urgent for assistive tech', () => {
    render(<Countdown remainingSeconds={45} anchorKey="a" />)
    expect(screen.getByRole('timer')).toHaveAttribute('aria-live', 'assertive')
  })
})
