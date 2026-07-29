import type { HiringReport } from '../api/examiner/types'

import './HiringReportPanel.css'

interface HiringReportPanelProps {
  report: HiringReport | null | undefined
}

const RECOMMENDATION_LABELS: Record<HiringReport['recommendation'], string> = {
  proceed: 'Proceed',
  maybe: 'Maybe',
  reject: 'Reject',
}

/**
 * Phase 2 Slice 8 — renders once ai's evaluation pipeline has produced a
 * report for this session. Generation is async and best-effort, so a
 * missing report (still generating, or nothing submitted) just means this
 * renders nothing — no error state.
 */
export function HiringReportPanel({ report }: HiringReportPanelProps) {
  if (!report) return null

  return (
    <section className="hiring-report" aria-label="Hiring report">
      <div className="hiring-report__header">
        <span className="hiring-report__badge">{report.seniority_match}</span>
        <span
          className={`hiring-report__chip hiring-report__chip--${report.recommendation}`}
        >
          {RECOMMENDATION_LABELS[report.recommendation]}
        </span>
      </div>

      <div className="hiring-report__score">
        <div className="hiring-report__score-bar">
          <div
            className="hiring-report__score-fill"
            style={{ width: `${Math.round(report.overall_score * 100)}%` }}
          />
        </div>
        <span className="hiring-report__score-label">
          {Math.round(report.overall_score * 100)}%
        </span>
      </div>

      <div className="hiring-report__areas">
        <div>
          <h3>Strong areas</h3>
          <ul className="hiring-report__tags">
            {report.strong_areas.map((area) => (
              <li key={area} className="hiring-report__tag hiring-report__tag--strong">
                {area}
              </li>
            ))}
            {report.strong_areas.length === 0 && <li className="hiring-report__tag-empty">—</li>}
          </ul>
        </div>
        <div>
          <h3>Weak areas</h3>
          <ul className="hiring-report__tags">
            {report.weak_areas.map((area) => (
              <li key={area} className="hiring-report__tag hiring-report__tag--weak">
                {area}
              </li>
            ))}
            {report.weak_areas.length === 0 && <li className="hiring-report__tag-empty">—</li>}
          </ul>
        </div>
      </div>

      <p className="hiring-report__narrative">
        <strong>Code quality:</strong> {report.code_quality}
      </p>
      <p className="hiring-report__narrative">
        <strong>Problem solving:</strong> {report.problem_solving}
      </p>

      <table className="hiring-report__evidence">
        <thead>
          <tr>
            <th scope="col">Question</th>
            <th scope="col">Verdict</th>
            <th scope="col">Approach</th>
            <th scope="col">Complexity</th>
            <th scope="col">Score</th>
          </tr>
        </thead>
        <tbody>
          {report.evidence.map((row) => (
            <tr key={row.question}>
              <td>{row.question}</td>
              <td>{row.verdict ?? '—'}</td>
              <td>{row.approach ?? '—'}</td>
              <td>{row.complexity ?? '—'}</td>
              <td>{row.partial_score.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
