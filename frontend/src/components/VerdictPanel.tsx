import type { SubmissionResponse, Verdict } from '../api/types'

import './VerdictPanel.css'

interface VerdictPanelProps {
  submission: SubmissionResponse | null
  /** True while the submit request itself is in flight. */
  pending?: boolean
}

const VERDICT_LABELS: Record<Verdict, string> = {
  AC: 'Accepted',
  WA: 'Wrong Answer',
  TLE: 'Time Limit Exceeded',
  MLE: 'Memory Limit Exceeded',
  RE: 'Runtime Error',
  CE: 'Compile Error',
}

function formatMemory(kb: number): string {
  return kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} kB`
}

export function VerdictPanel({ submission, pending = false }: VerdictPanelProps) {
  if (pending || !submission) {
    return (
      <section className="verdicts" aria-label="Results">
        <p className="verdicts__empty">
          {pending ? 'Sending your code to the judge…' : 'No results yet.'}
        </p>
      </section>
    )
  }

  const running = submission.status === 'queued' || submission.status === 'running'

  if (running) {
    return (
      <section className="verdicts" aria-label="Results">
        <p className="verdicts__empty" role="status">
          Judging…
        </p>
      </section>
    )
  }

  if (submission.status === 'compile_error') {
    return (
      <section className="verdicts" aria-label="Results">
        <p className="verdicts__summary verdicts__summary--CE">
          {VERDICT_LABELS.CE}
        </p>
        <pre className="verdicts__compile-error">{submission.compile_error}</pre>
      </section>
    )
  }

  const summary = submission.summary_verdict

  return (
    <section className="verdicts" aria-label="Results">
      {summary && (
        <p className={`verdicts__summary verdicts__summary--${summary}`}>
          {VERDICT_LABELS[summary]}
          <span className="verdicts__mode">
            {submission.mode === 'run' ? ' (sample cases)' : ' (all cases)'}
          </span>
        </p>
      )}
      <table className="verdicts__table">
        <thead>
          <tr>
            <th scope="col">Case</th>
            <th scope="col">Verdict</th>
            <th scope="col">Time</th>
            <th scope="col">Memory</th>
          </tr>
        </thead>
        <tbody>
          {submission.cases.map((testCase) => (
            <tr key={testCase.ordinal}>
              <td>{testCase.ordinal}</td>
              <td>
                <span className={`verdict verdict--${testCase.verdict}`}>
                  {testCase.verdict}
                </span>
              </td>
              <td>{testCase.runtime_ms} ms</td>
              <td>{formatMemory(testCase.memory_kb)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
