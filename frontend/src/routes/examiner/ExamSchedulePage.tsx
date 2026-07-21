import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { ApiError } from '../../api/client'
import {
  listBlueprints,
  listExams,
  scheduleExam,
} from '../../api/examiner/endpoints'
import type { ExamScheduled } from '../../api/examiner/types'

function toIsoLocal(offsetMinutes: number): string {
  const when = new Date(Date.now() + offsetMinutes * 60_000)
  // datetime-local wants a value without the timezone suffix.
  return new Date(when.getTime() - when.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16)
}

export function ExamSchedulePage() {
  const queryClient = useQueryClient()
  const blueprints = useQuery({
    queryKey: ['blueprints'],
    queryFn: listBlueprints,
  })
  const exams = useQuery({ queryKey: ['exams'], queryFn: listExams })

  const [email, setEmail] = useState('')
  const [blueprintId, setBlueprintId] = useState('')
  const [startsAt, setStartsAt] = useState(() => toIsoLocal(-1))
  const [endsAt, setEndsAt] = useState(() => toIsoLocal(120))
  const [scheduled, setScheduled] = useState<ExamScheduled | null>(null)
  const [error, setError] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () =>
      scheduleExam({
        candidate_email: email,
        blueprint_id: blueprintId,
        // datetime-local is timezone-naive; send an absolute instant.
        starts_at: new Date(startsAt).toISOString(),
        ends_at: new Date(endsAt).toISOString(),
      }),
    onSuccess: (created) => {
      setScheduled(created)
      setEmail('')
      void queryClient.invalidateQueries({ queryKey: ['exams'] })
    },
    onError: (caught) =>
      setError(
        caught instanceof ApiError ? caught.detail : 'Could not schedule the exam.',
      ),
  })

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setScheduled(null)
    create.mutate()
  }

  return (
    <section>
      <h1>Schedule an exam</h1>
      <form className="console-form" onSubmit={handleSubmit}>
        <label>
          <span>Candidate email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label>
          <span>Blueprint</span>
          <select
            value={blueprintId}
            onChange={(e) => setBlueprintId(e.target.value)}
            required
          >
            <option value="">Select a blueprint…</option>
            {(blueprints.data ?? []).map((blueprint) => (
              <option key={blueprint.id} value={blueprint.id}>
                {blueprint.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Window opens</span>
          <input
            type="datetime-local"
            value={startsAt}
            onChange={(e) => setStartsAt(e.target.value)}
            required
          />
        </label>
        <label>
          <span>Window closes</span>
          <input
            type="datetime-local"
            value={endsAt}
            onChange={(e) => setEndsAt(e.target.value)}
            required
          />
        </label>
        <button type="submit" className="console-button" disabled={create.isPending}>
          {create.isPending ? 'Scheduling…' : 'Schedule & send invite'}
        </button>
        {error && (
          <p className="console-error" role="alert">
            {error}
          </p>
        )}
      </form>

      {scheduled && (
        <div className="schedule-result" role="status">
          <p>
            Invite sent to <strong>{scheduled.candidate_email}</strong> (
            {scheduled.invite?.status ?? 'pending'}).
          </p>
          {scheduled.invite_link && (
            <p className="schedule-result__link">
              Dev invite link: <code>{scheduled.invite_link}</code>
            </p>
          )}
        </div>
      )}

      <h2>Scheduled exams</h2>
      {exams.data && exams.data.length > 0 ? (
        <table className="console-table">
          <thead>
            <tr>
              <th scope="col">Candidate</th>
              <th scope="col">Opens</th>
              <th scope="col">Closes</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {exams.data.map((exam) => (
              <tr key={exam.id}>
                <td>{exam.candidate_email}</td>
                <td>{new Date(exam.starts_at).toLocaleString()}</td>
                <td>{new Date(exam.ends_at).toLocaleString()}</td>
                <td>{exam.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p>No exams scheduled yet.</p>
      )}
    </section>
  )
}
