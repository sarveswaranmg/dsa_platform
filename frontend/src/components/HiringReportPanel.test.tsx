import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { HiringReport } from '../api/examiner/types'
import { HiringReportPanel } from './HiringReportPanel'

function report(overrides: Partial<HiringReport> = {}): HiringReport {
  return {
    seniority_match: 'SDE-2',
    strong_areas: ['graphs', 'heaps'],
    weak_areas: ['DP'],
    code_quality: 'production-grade',
    problem_solving: 'optimal approach, implementation errors',
    overall_score: 0.78,
    recommendation: 'proceed',
    evidence: [
      {
        question: 'Shortest Path',
        verdict: 'AC',
        approach: 'BFS',
        complexity: 'O(V+E)',
        partial_score: 1.0,
      },
    ],
    generated_at: '2026-07-29T00:00:00Z',
    ...overrides,
  }
}

describe('HiringReportPanel', () => {
  it('renders nothing when there is no report', () => {
    const { container } = render(<HiringReportPanel report={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing while the report is still loading', () => {
    const { container } = render(<HiringReportPanel report={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders the seniority badge, recommendation chip, and score', () => {
    render(<HiringReportPanel report={report()} />)
    expect(screen.getByText('SDE-2')).toBeInTheDocument()
    expect(screen.getByText('Proceed')).toBeInTheDocument()
    expect(screen.getByText('78%')).toBeInTheDocument()
  })

  it('renders strong and weak area tags', () => {
    render(<HiringReportPanel report={report()} />)
    expect(screen.getByText('graphs')).toBeInTheDocument()
    expect(screen.getByText('heaps')).toBeInTheDocument()
    expect(screen.getByText('DP')).toBeInTheDocument()
  })

  it('renders the evidence table with one row per question', () => {
    render(<HiringReportPanel report={report()} />)
    expect(screen.getByText('Shortest Path')).toBeInTheDocument()
    expect(screen.getByText('BFS')).toBeInTheDocument()
    expect(screen.getByText('O(V+E)')).toBeInTheDocument()
  })

  it('falls back to a placeholder when an area list is empty', () => {
    render(<HiringReportPanel report={report({ weak_areas: [] })} />)
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })
})
