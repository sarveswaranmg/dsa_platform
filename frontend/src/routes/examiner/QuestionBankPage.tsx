import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { listQuestions, listTopics } from '../../api/examiner/endpoints'
import type { QuestionStatus } from '../../api/examiner/types'

export function QuestionBankPage() {
  const [topicId, setTopicId] = useState('')
  const [difficulty, setDifficulty] = useState('')
  const [status, setStatus] = useState('')

  const topics = useQuery({ queryKey: ['topics'], queryFn: listTopics })
  const questions = useQuery({
    queryKey: ['questions', topicId, difficulty, status],
    queryFn: () =>
      listQuestions({
        topicId: topicId || undefined,
        difficulty: difficulty ? Number(difficulty) : undefined,
        status: status || undefined,
      }),
  })

  return (
    <section>
      <div className="console-heading">
        <h1>Question bank</h1>
        <Link className="console-button" to="/console/questions/new">
          New question
        </Link>
      </div>

      <div className="console-filters">
        <label>
          <span>Topic</span>
          <select value={topicId} onChange={(e) => setTopicId(e.target.value)}>
            <option value="">All topics</option>
            {(topics.data ?? []).map((topic) => (
              <option key={topic.id} value={topic.id}>
                {topic.parent_id ? '— ' : ''}
                {topic.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Difficulty</span>
          <select
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value)}
          >
            <option value="">Any</option>
            {[1, 2, 3, 4, 5].map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Status</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as QuestionStatus | '')}
          >
            <option value="">Any</option>
            <option value="draft">Draft</option>
            <option value="published">Published</option>
            <option value="archived">Archived</option>
          </select>
        </label>
      </div>

      {questions.isLoading && <p>Loading questions…</p>}
      {questions.data && questions.data.length === 0 && (
        <p>No questions match these filters.</p>
      )}
      {questions.data && questions.data.length > 0 && (
        <table className="console-table">
          <thead>
            <tr>
              <th scope="col">Title</th>
              <th scope="col">Difficulty</th>
              <th scope="col">Status</th>
              <th scope="col">Version</th>
            </tr>
          </thead>
          <tbody>
            {questions.data.map((question) => (
              <tr key={question.id}>
                <td>
                  <Link to={`/console/questions/${question.id}`}>
                    {question.title}
                  </Link>
                </td>
                <td>{question.difficulty}</td>
                <td>{question.status}</td>
                <td>v{question.version_number}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
