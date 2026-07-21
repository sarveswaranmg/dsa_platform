import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import type { SubmissionResponse } from '../../api/types'
import {
  getSubmissionDetail,
  listExamSubmissions,
  listExams,
} from '../../api/examiner/endpoints'
import { CodeViewer } from '../../components/examiner/CodeViewer'
import { VerdictPanel } from '../../components/VerdictPanel'

import './ResultsPage.css'

export function ResultsPage() {
  const [examId, setExamId] = useState<string | null>(null)
  const [submissionId, setSubmissionId] = useState<string | null>(null)

  const exams = useQuery({ queryKey: ['exams'], queryFn: listExams })
  const submissions = useQuery({
    queryKey: ['exam-submissions', examId],
    queryFn: () => listExamSubmissions(examId!),
    enabled: examId !== null,
  })
  const detail = useQuery({
    queryKey: ['submission-detail', submissionId],
    queryFn: () => getSubmissionDetail(submissionId!),
    enabled: submissionId !== null,
  })

  return (
    <section className="results">
      <h1>Results</h1>
      <div className="results__grid">
        <div>
          <h2>Candidates</h2>
          <ul className="results__list">
            {(exams.data ?? []).map((exam) => (
              <li key={exam.id}>
                <button
                  type="button"
                  className={`results__item${
                    exam.id === examId ? ' results__item--active' : ''
                  }`}
                  onClick={() => {
                    setExamId(exam.id)
                    setSubmissionId(null)
                  }}
                >
                  <span>{exam.candidate_email}</span>
                  <small>{new Date(exam.starts_at).toLocaleDateString()}</small>
                </button>
              </li>
            ))}
          </ul>
          {exams.data?.length === 0 && <p>No exams scheduled.</p>}
        </div>

        <div>
          <h2>Submissions</h2>
          {examId === null && <p>Select a candidate.</p>}
          {examId !== null && submissions.data?.length === 0 && (
            <p>This candidate has not submitted anything yet.</p>
          )}
          {submissions.data && submissions.data.length > 0 && (
            <table className="console-table">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Lang</th>
                  <th scope="col">Mode</th>
                  <th scope="col">Verdict</th>
                </tr>
              </thead>
              <tbody>
                {submissions.data.map((submission) => (
                  <tr
                    key={submission.id}
                    className={
                      submission.id === submissionId ? 'results__row--active' : ''
                    }
                  >
                    <td>
                      <button
                        type="button"
                        className="results__link"
                        onClick={() => setSubmissionId(submission.id)}
                      >
                        {new Date(submission.created_at).toLocaleTimeString()}
                      </button>
                    </td>
                    <td>{submission.language}</td>
                    <td>{submission.mode}</td>
                    <td>{submission.summary_verdict ?? submission.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {detail.data && (
        <div className="results__detail">
          <h2>Submitted code</h2>
          <CodeViewer
            language={detail.data.language}
            source={detail.data.source}
          />
          <VerdictPanel
            submission={
              {
                ...detail.data,
                // The examiner detail shape is a superset of the candidate one.
                exam_id: detail.data.exam_id,
              } as unknown as SubmissionResponse
            }
          />
        </div>
      )}
    </section>
  )
}
