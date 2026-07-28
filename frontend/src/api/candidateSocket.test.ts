import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setExamToken, clearExamToken } from '../auth/examToken'
import { connectCandidateSocket } from './candidateSocket'

class MockWebSocket {
  static instances: MockWebSocket[] = []
  static readonly OPEN = 1

  readyState = MockWebSocket.OPEN
  onmessage: ((event: { data: string }) => void) | null = null
  sent: string[] = []
  closed = false

  constructor(readonly url: string) {
    MockWebSocket.instances.push(this)
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.closed = true
  }

  emit(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) })
  }

  emitRaw(data: string): void {
    this.onmessage?.({ data })
  }
}

describe('connectCandidateSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    setExamToken('tok-123')
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    clearExamToken()
  })

  it('does nothing when there is no exam token', () => {
    clearExamToken()
    const socket = connectCandidateSocket({
      getOrdinal: () => 1,
      getSource: () => 'x',
      onFollowupPushed: vi.fn(),
      onVerdict: vi.fn(),
    })
    expect(MockWebSocket.instances).toHaveLength(0)
    expect(() => socket.close()).not.toThrow()
  })

  it('connects with the token as a query param', () => {
    connectCandidateSocket({
      getOrdinal: () => null,
      getSource: () => '',
      onFollowupPushed: vi.fn(),
      onVerdict: vi.fn(),
    })
    expect(MockWebSocket.instances).toHaveLength(1)
    expect(MockWebSocket.instances[0].url).toContain('/candidate/session/ws?token=tok-123')
  })

  it('pushes a code_snapshot frame on the configured interval', () => {
    connectCandidateSocket({
      getOrdinal: () => 2,
      getSource: () => 'print(1)',
      onFollowupPushed: vi.fn(),
      onVerdict: vi.fn(),
      snapshotIntervalMs: 1000,
    })
    const ws = MockWebSocket.instances[0]
    expect(ws.sent).toHaveLength(0)

    vi.advanceTimersByTime(1000)
    expect(ws.sent).toHaveLength(1)
    expect(JSON.parse(ws.sent[0])).toEqual({
      type: 'code_snapshot',
      ordinal: 2,
      source: 'print(1)',
    })

    vi.advanceTimersByTime(1000)
    expect(ws.sent).toHaveLength(2)
  })

  it('never sends a snapshot while no question is active', () => {
    connectCandidateSocket({
      getOrdinal: () => null,
      getSource: () => 'unused',
      onFollowupPushed: vi.fn(),
      onVerdict: vi.fn(),
      snapshotIntervalMs: 1000,
    })
    vi.advanceTimersByTime(5000)
    expect(MockWebSocket.instances[0].sent).toHaveLength(0)
  })

  it('surfaces a followup_pushed event', () => {
    const onFollowupPushed = vi.fn()
    connectCandidateSocket({
      getOrdinal: () => 1,
      getSource: () => '',
      onFollowupPushed,
      onVerdict: vi.fn(),
    })
    MockWebSocket.instances[0].emit({
      type: 'followup_pushed',
      payload: {
        previous_version_id: 'v1',
        new_version_id: 'v2',
        summary: 'n can now be up to 10^6.',
      },
    })
    expect(onFollowupPushed).toHaveBeenCalledWith({
      previousVersionId: 'v1',
      newVersionId: 'v2',
      summary: 'n can now be up to 10^6.',
    })
  })

  it('surfaces a verdict event', () => {
    const onVerdict = vi.fn()
    connectCandidateSocket({
      getOrdinal: () => 1,
      getSource: () => '',
      onFollowupPushed: vi.fn(),
      onVerdict,
    })
    MockWebSocket.instances[0].emit({ type: 'verdict', payload: { submission_id: 's1' } })
    expect(onVerdict).toHaveBeenCalledOnce()
  })

  it('ignores malformed frames without throwing', () => {
    const onFollowupPushed = vi.fn()
    const onVerdict = vi.fn()
    connectCandidateSocket({
      getOrdinal: () => 1,
      getSource: () => '',
      onFollowupPushed,
      onVerdict,
    })
    expect(() => MockWebSocket.instances[0].emitRaw('not json')).not.toThrow()
    expect(onFollowupPushed).not.toHaveBeenCalled()
    expect(onVerdict).not.toHaveBeenCalled()
  })

  it('close() stops the snapshot timer and closes the socket', () => {
    const socket = connectCandidateSocket({
      getOrdinal: () => 1,
      getSource: () => 'x',
      onFollowupPushed: vi.fn(),
      onVerdict: vi.fn(),
      snapshotIntervalMs: 1000,
    })
    const ws = MockWebSocket.instances[0]
    socket.close()
    expect(ws.closed).toBe(true)

    vi.advanceTimersByTime(5000)
    expect(ws.sent).toHaveLength(0)
  })
})
