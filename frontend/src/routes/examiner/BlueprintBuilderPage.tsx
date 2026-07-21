import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { ApiError } from '../../api/client'
import {
  createBlueprint,
  listBlueprints,
  listTopics,
} from '../../api/examiner/endpoints'
import type { TopicMixEntry } from '../../api/examiner/types'
import {
  emptyEntry,
  TopicMixEditor,
  validateTopicMix,
} from '../../components/examiner/TopicMixEditor'

export function BlueprintBuilderPage() {
  const queryClient = useQueryClient()
  const topics = useQuery({ queryKey: ['topics'], queryFn: listTopics })
  const blueprints = useQuery({
    queryKey: ['blueprints'],
    queryFn: listBlueprints,
  })

  const [name, setName] = useState('')
  const [targetRole, setTargetRole] = useState('Backend Engineer')
  const [experienceBand, setExperienceBand] = useState('senior')
  const [duration, setDuration] = useState(90)
  const [entries, setEntries] = useState<TopicMixEntry[]>([emptyEntry()])
  const [error, setError] = useState<string | null>(null)

  const problems = validateTopicMix(entries)
  const canSubmit = problems.length === 0 && name.trim().length > 0

  const create = useMutation({
    mutationFn: () =>
      createBlueprint({
        name,
        target_role: targetRole,
        experience_band: experienceBand,
        total_duration_minutes: duration,
        topic_mix: entries,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['blueprints'] })
      setName('')
      setEntries([emptyEntry()])
    },
    onError: (caught) =>
      setError(
        caught instanceof ApiError ? caught.detail : 'Could not save blueprint.',
      ),
  })

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    create.mutate()
  }

  return (
    <section>
      <h1>Blueprints</h1>

      <form className="console-form" onSubmit={handleSubmit} style={{ maxWidth: 'none' }}>
        <div className="question-editor__row">
          <label>
            <span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label>
            <span>Target role</span>
            <input
              value={targetRole}
              onChange={(e) => setTargetRole(e.target.value)}
              required
            />
          </label>
          <label>
            <span>Experience band</span>
            <input
              value={experienceBand}
              onChange={(e) => setExperienceBand(e.target.value)}
              required
            />
          </label>
        </div>
        <label style={{ maxWidth: '16rem' }}>
          <span>Total duration (minutes)</span>
          <input
            type="number"
            min={1}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
          />
        </label>

        <h2>Topic mix</h2>
        <TopicMixEditor
          topics={topics.data ?? []}
          entries={entries}
          onChange={setEntries}
        />

        <button
          type="submit"
          className="console-button"
          disabled={!canSubmit || create.isPending}
        >
          {create.isPending ? 'Saving…' : 'Create blueprint'}
        </button>
        {error && (
          <p className="console-error" role="alert">
            {error}
          </p>
        )}
      </form>

      <h2>Existing blueprints</h2>
      {blueprints.data && blueprints.data.length > 0 ? (
        <table className="console-table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Role</th>
              <th scope="col">Duration</th>
              <th scope="col">Topics</th>
              <th scope="col">Version</th>
            </tr>
          </thead>
          <tbody>
            {blueprints.data.map((blueprint) => (
              <tr key={blueprint.id}>
                <td>{blueprint.name}</td>
                <td>{blueprint.current_version.target_role}</td>
                <td>{blueprint.current_version.total_duration_minutes} min</td>
                <td>{blueprint.current_version.topic_mix.length}</td>
                <td>v{blueprint.current_version.version_number}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p>No blueprints yet.</p>
      )}
    </section>
  )
}
