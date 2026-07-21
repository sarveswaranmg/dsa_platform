import { useEffect, useState } from 'react'

import './Countdown.css'

interface CountdownProps {
  /** Seconds left, as reported by the server on the most recent fetch. */
  remainingSeconds: number
  /** Changes whenever a fresh server value arrives, re-anchoring the clock. */
  anchorKey: string | number
  onExpire?: () => void
}

export function formatDuration(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds))
  const hours = Math.floor(safe / 3600)
  const minutes = Math.floor((safe % 3600) / 60)
  const seconds = safe % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(seconds)}`
    : `${pad(minutes)}:${pad(seconds)}`
}

/**
 * Server-authoritative countdown. It anchors on the server's remaining_seconds
 * plus a local monotonic reading and counts down from there, re-anchoring each
 * time the server reports again — the client's wall clock is never trusted.
 */
export function Countdown({
  remainingSeconds,
  anchorKey,
  onExpire,
}: CountdownProps) {
  const [displayed, setDisplayed] = useState(remainingSeconds)

  useEffect(() => {
    const anchoredAt = Date.now()
    setDisplayed(remainingSeconds)

    const tick = () => {
      const elapsed = Math.floor((Date.now() - anchoredAt) / 1000)
      setDisplayed(Math.max(0, remainingSeconds - elapsed))
    }
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [remainingSeconds, anchorKey])

  useEffect(() => {
    if (displayed === 0) onExpire?.()
  }, [displayed, onExpire])

  const expired = displayed === 0
  const urgent = !expired && displayed <= 60

  return (
    <div
      className={`countdown${urgent ? ' countdown--urgent' : ''}${expired ? ' countdown--expired' : ''}`}
      role="timer"
      aria-live={urgent ? 'assertive' : 'off'}
    >
      <span className="countdown__label">
        {expired ? 'Time is up' : 'Time remaining'}
      </span>
      <span className="countdown__value">{formatDuration(displayed)}</span>
    </div>
  )
}
