import { getExamToken } from '../auth/examToken'
import type { RequirementsChange } from '../components/RequirementsChangedBanner'

/** How often the candidate's current editor buffer is pushed as a
 *  `code_snapshot` event (Phase 2 Slice 6) — the proctor's live view. */
const SNAPSHOT_INTERVAL_MS = 30_000

export interface CandidateSocketOptions {
  getOrdinal: () => number | null
  getSource: () => string
  onFollowupPushed: (change: RequirementsChange) => void
  onVerdict: () => void
  snapshotIntervalMs?: number
}

export interface CandidateSocket {
  close: () => void
}

interface InboundFrame {
  type?: string
  payload?: Record<string, unknown>
}

/** Same-origin relative paths (the default) work unmodified for local dev
 *  and the nginx-proxied Docker build, mirroring `api/client.ts`'s
 *  `API_BASE_URL` handling — just converted to a ws(s):// scheme. */
function websocketUrl(path: string, token: string): string {
  const configured = import.meta.env.VITE_API_BASE_URL
  const origin = configured
    ? configured.replace(/^http/, 'ws')
    : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
  return `${origin}${path}?token=${encodeURIComponent(token)}`
}

/** A no-op socket handle — used when there's no exam token yet (nothing to
 *  connect with) so callers never need to null-check the return value. */
function noopSocket(): CandidateSocket {
  return { close: () => {} }
}

/**
 * Opens the candidate's live WebSocket connection: pushes a `code_snapshot`
 * every 30s with the current editor buffer (the proctor's live view), and
 * surfaces `followup_pushed`/`verdict` events pushed back from the server.
 *
 * Not a hook itself — callers wire it into a `useEffect` so the connection
 * lifetime matches whatever the caller considers "this exam session is
 * active" (see ExamRoomPage.tsx).
 */
export function connectCandidateSocket(options: CandidateSocketOptions): CandidateSocket {
  const token = getExamToken()
  if (!token) return noopSocket()

  const socket = new WebSocket(websocketUrl('/candidate/session/ws', token))

  socket.onmessage = (event: MessageEvent<string>) => {
    let frame: InboundFrame
    try {
      frame = JSON.parse(event.data) as InboundFrame
    } catch {
      return // malformed frame — ignore, never crash the exam room over it
    }
    if (frame.type === 'followup_pushed' && frame.payload) {
      const { previous_version_id, new_version_id, summary } = frame.payload
      options.onFollowupPushed({
        previousVersionId: String(previous_version_id),
        newVersionId: String(new_version_id),
        summary: String(summary),
      })
    } else if (frame.type === 'verdict') {
      options.onVerdict()
    }
  }

  const intervalId = window.setInterval(() => {
    const ordinal = options.getOrdinal()
    if (socket.readyState === WebSocket.OPEN && ordinal !== null) {
      socket.send(
        JSON.stringify({ type: 'code_snapshot', ordinal, source: options.getSource() }),
      )
    }
  }, options.snapshotIntervalMs ?? SNAPSHOT_INTERVAL_MS)

  return {
    close: () => {
      window.clearInterval(intervalId)
      socket.close()
    },
  }
}
