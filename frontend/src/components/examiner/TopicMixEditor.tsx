import type { TopicMixEntry, Topic } from '../../api/examiner/types'

import './TopicMixEditor.css'

export const REQUIRED_WEIGHT_TOTAL = 100

export function totalWeight(entries: TopicMixEntry[]): number {
  return entries.reduce((sum, entry) => sum + (Number(entry.weight) || 0), 0)
}

export interface MixProblem {
  message: string
}

/** Mirrors the server-side validation in schemas/blueprint.py so the examiner
 *  sees the same rules live instead of discovering them via a 422. */
export function validateTopicMix(entries: TopicMixEntry[]): MixProblem[] {
  const problems: MixProblem[] = []
  if (entries.length === 0) {
    problems.push({ message: 'Add at least one topic.' })
    return problems
  }
  const total = totalWeight(entries)
  if (total !== REQUIRED_WEIGHT_TOTAL) {
    problems.push({
      message: `Weights must sum to ${REQUIRED_WEIGHT_TOTAL} (currently ${total}).`,
    })
  }
  if (entries.some((entry) => !entry.topic_id)) {
    problems.push({ message: 'Every row needs a topic.' })
  }
  const ids = entries.map((entry) => entry.topic_id).filter(Boolean)
  if (new Set(ids).size !== ids.length) {
    problems.push({ message: 'A topic can only appear once.' })
  }
  if (entries.some((entry) => entry.difficulty_min > entry.difficulty_max)) {
    problems.push({ message: 'Difficulty range must go low to high.' })
  }
  if (entries.some((entry) => entry.question_count < 1)) {
    problems.push({ message: 'Each topic needs at least one question.' })
  }
  return problems
}

export function emptyEntry(): TopicMixEntry {
  return {
    topic_id: '',
    weight: 100,
    difficulty_min: 1,
    difficulty_max: 3,
    question_count: 1,
  }
}

interface TopicMixEditorProps {
  topics: Topic[]
  entries: TopicMixEntry[]
  onChange: (entries: TopicMixEntry[]) => void
}

export function TopicMixEditor({
  topics,
  entries,
  onChange,
}: TopicMixEditorProps) {
  const total = totalWeight(entries)
  const problems = validateTopicMix(entries)

  function update(index: number, patch: Partial<TopicMixEntry>) {
    onChange(entries.map((entry, i) => (i === index ? { ...entry, ...patch } : entry)))
  }

  return (
    <div className="topic-mix">
      <table className="console-table">
        <thead>
          <tr>
            <th scope="col">Topic</th>
            <th scope="col">Weight</th>
            <th scope="col">Difficulty</th>
            <th scope="col">Questions</th>
            <th scope="col" />
          </tr>
        </thead>
        <tbody>
          {entries.map((entry, index) => (
            <tr key={index}>
              <td>
                <select
                  aria-label={`Topic for row ${index + 1}`}
                  value={entry.topic_id}
                  onChange={(event) =>
                    update(index, { topic_id: event.target.value })
                  }
                >
                  <option value="">Select a topic…</option>
                  {topics.map((topic) => (
                    <option key={topic.id} value={topic.id}>
                      {topic.name}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <input
                  type="number"
                  aria-label={`Weight for row ${index + 1}`}
                  min={1}
                  max={100}
                  value={entry.weight}
                  onChange={(event) =>
                    update(index, { weight: Number(event.target.value) })
                  }
                />
              </td>
              <td className="topic-mix__range">
                <input
                  type="number"
                  aria-label={`Minimum difficulty for row ${index + 1}`}
                  min={1}
                  max={5}
                  value={entry.difficulty_min}
                  onChange={(event) =>
                    update(index, { difficulty_min: Number(event.target.value) })
                  }
                />
                <span>–</span>
                <input
                  type="number"
                  aria-label={`Maximum difficulty for row ${index + 1}`}
                  min={1}
                  max={5}
                  value={entry.difficulty_max}
                  onChange={(event) =>
                    update(index, { difficulty_max: Number(event.target.value) })
                  }
                />
              </td>
              <td>
                <input
                  type="number"
                  aria-label={`Question count for row ${index + 1}`}
                  min={1}
                  value={entry.question_count}
                  onChange={(event) =>
                    update(index, { question_count: Number(event.target.value) })
                  }
                />
              </td>
              <td>
                <button
                  type="button"
                  className="topic-mix__remove"
                  onClick={() => onChange(entries.filter((_, i) => i !== index))}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="topic-mix__footer">
        <button
          type="button"
          className="console-button console-button--secondary"
          onClick={() => onChange([...entries, emptyEntry()])}
        >
          Add topic
        </button>
        <span
          className={`topic-mix__total${
            total === REQUIRED_WEIGHT_TOTAL ? ' topic-mix__total--ok' : ''
          }`}
          data-testid="weight-total"
        >
          Total weight: {total} / {REQUIRED_WEIGHT_TOTAL}
        </span>
      </div>

      {problems.length > 0 && (
        <ul className="topic-mix__problems" role="alert">
          {problems.map((problem) => (
            <li key={problem.message}>{problem.message}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
