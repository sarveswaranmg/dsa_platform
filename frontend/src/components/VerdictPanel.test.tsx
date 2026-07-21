import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { SubmissionResponse } from '../api/types'
import { VerdictPanel } from './VerdictPanel'

function submission(
  overrides: Partial<SubmissionResponse> = {},
): SubmissionResponse {
  return {
    id: 'sub-1',
    exam_id: 'exam-1',
    question_version_id: 'ver-1',
    language: 'python',
    mode: 'submit',
    status: 'completed',
    summary_verdict: 'AC',
    compile_error: null,
    cases: [],
    ...overrides,
  }
}

describe('VerdictPanel', () => {
  it('shows an empty state before anything is submitted', () => {
    render(<VerdictPanel submission={null} />)
    expect(screen.getByText('No results yet.')).toBeInTheDocument()
  })

  it('shows a pending state while the submit is in flight', () => {
    render(<VerdictPanel submission={null} pending />)
    expect(screen.getByText(/sending your code/i)).toBeInTheDocument()
  })

  it('shows a judging state while the verdict is still queued', () => {
    render(
      <VerdictPanel
        submission={submission({ status: 'queued', summary_verdict: null })}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Judging…')
  })

  it('renders a per-case row with runtime and memory for an accepted run', () => {
    render(
      <VerdictPanel
        submission={submission({
          cases: [
            { ordinal: 1, verdict: 'AC', runtime_ms: 20, memory_kb: 15132 },
          ],
        })}
      />,
    )
    expect(screen.getByText('Accepted')).toBeInTheDocument()
    expect(screen.getByText('AC')).toBeInTheDocument()
    expect(screen.getByText('20 ms')).toBeInTheDocument()
    // kB is rendered as MB once it crosses 1024.
    expect(screen.getByText('14.8 MB')).toBeInTheDocument()
  })

  it('renders every failing verdict kind', () => {
    render(
      <VerdictPanel
        submission={submission({
          summary_verdict: 'WA',
          cases: [
            { ordinal: 1, verdict: 'AC', runtime_ms: 5, memory_kb: 100 },
            { ordinal: 2, verdict: 'WA', runtime_ms: 6, memory_kb: 100 },
            { ordinal: 3, verdict: 'TLE', runtime_ms: 2000, memory_kb: 100 },
            { ordinal: 4, verdict: 'MLE', runtime_ms: 10, memory_kb: 262144 },
            { ordinal: 5, verdict: 'RE', runtime_ms: 8, memory_kb: 100 },
          ],
        })}
      />,
    )
    expect(screen.getByText('Wrong Answer')).toBeInTheDocument()
    for (const verdict of ['AC', 'WA', 'TLE', 'MLE', 'RE']) {
      expect(screen.getByText(verdict)).toBeInTheDocument()
    }
    expect(screen.getAllByRole('row')).toHaveLength(6) // header + 5 cases
  })

  it('distinguishes a sample-only run from a full submit', () => {
    render(
      <VerdictPanel
        submission={submission({
          mode: 'run',
          cases: [{ ordinal: 1, verdict: 'AC', runtime_ms: 5, memory_kb: 100 }],
        })}
      />,
    )
    expect(screen.getByText(/sample cases/i)).toBeInTheDocument()
  })

  it('renders the compiler output on a compile error', () => {
    render(
      <VerdictPanel
        submission={submission({
          status: 'compile_error',
          summary_verdict: 'CE',
          compile_error: "main.cpp:1: error: expected ';'",
          cases: [],
        })}
      />,
    )
    expect(screen.getByText('Compile Error')).toBeInTheDocument()
    expect(screen.getByText(/expected ';'/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
