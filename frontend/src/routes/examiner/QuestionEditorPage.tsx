import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import Markdown from 'react-markdown'
import { useNavigate, useParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import {
  createQuestion,
  createTestCase,
  getQuestion,
  listTestCases,
  listTopics,
  publishQuestion,
  updateQuestion,
  uploadToPresignedUrl,
} from '../../api/examiner/endpoints'
import type { QuestionPayload } from '../../api/examiner/types'

import './QuestionEditorPage.css'

const BLANK: QuestionPayload = {
  title: '',
  statement_md: '',
  constraints_md: '',
  difficulty: 1,
  time_limit_ms: 2000,
  memory_limit_mb: 256,
  starter_code: {},
  topic_ids: [],
}

export function QuestionEditorPage() {
  const { questionId } = useParams<{ questionId: string }>()
  const isNew = !questionId || questionId === 'new'
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [draft, setDraft] = useState<QuestionPayload>(BLANK)
  const [loadedId, setLoadedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const topics = useQuery({ queryKey: ['topics'], queryFn: listTopics })

  const question = useQuery({
    queryKey: ['question', questionId],
    queryFn: () => getQuestion(questionId!),
    enabled: !isNew,
  })

  // Seed the form once the question arrives.
  if (!isNew && question.data && loadedId !== question.data.id) {
    const version = question.data.current_version
    setLoadedId(question.data.id)
    setDraft({
      title: version.title,
      statement_md: version.statement_md,
      constraints_md: version.constraints_md,
      difficulty: version.difficulty,
      time_limit_ms: version.time_limit_ms,
      memory_limit_mb: version.memory_limit_mb,
      starter_code: version.starter_code,
      topic_ids: question.data.topic_ids,
    })
  }

  const testCases = useQuery({
    queryKey: ['test-cases', questionId],
    queryFn: () => listTestCases(questionId!),
    enabled: !isNew,
  })

  const save = useMutation({
    mutationFn: () =>
      isNew ? createQuestion(draft) : updateQuestion(questionId!, draft),
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ['questions'] })
      void queryClient.invalidateQueries({ queryKey: ['question', saved.id] })
      if (isNew) navigate(`/console/questions/${saved.id}`, { replace: true })
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.detail : 'Could not save.'),
  })

  const publish = useMutation({
    mutationFn: () => publishQuestion(questionId!),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['question', questionId] })
      void queryClient.invalidateQueries({ queryKey: ['questions'] })
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.detail : 'Could not publish.'),
  })

  // Create the metadata row, then PUT both files straight to S3 using the
  // presigned URLs — the bytes never pass through our API.
  const addTestCase = useMutation({
    mutationFn: async (vars: {
      input: string
      expected: string
      isSample: boolean
    }) => {
      const created = await createTestCase(questionId!, vars.isSample)
      await uploadToPresignedUrl(created.upload_input_url, vars.input)
      await uploadToPresignedUrl(created.upload_output_url, vars.expected)
      return created
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['test-cases', questionId] })
      void queryClient.invalidateQueries({ queryKey: ['question', questionId] })
    },
    onError: (caught) =>
      setError(
        caught instanceof ApiError
          ? caught.detail
          : 'Upload failed — check the bucket CORS policy.',
      ),
  })

  const [tcInput, setTcInput] = useState('')
  const [tcExpected, setTcExpected] = useState('')
  const [tcIsSample, setTcIsSample] = useState(true)

  function handleSave(event: FormEvent) {
    event.preventDefault()
    setError(null)
    save.mutate()
  }

  return (
    <section>
      <div className="console-heading">
        <h1>{isNew ? 'New question' : draft.title || 'Question'}</h1>
        {!isNew && question.data && (
          <div className="editor-actions">
            <span className="editor-status">{question.data.status}</span>
            <button
              type="button"
              className="console-button console-button--secondary"
              onClick={() => publish.mutate()}
              disabled={publish.isPending}
            >
              Publish current version
            </button>
          </div>
        )}
      </div>

      {error && (
        <p className="console-error" role="alert">
          {error}
        </p>
      )}

      <form className="question-editor" onSubmit={handleSave}>
        <div className="question-editor__fields console-form">
          <label>
            <span>Title</span>
            <input
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              required
            />
          </label>
          <label>
            <span>Statement (markdown)</span>
            <textarea
              rows={10}
              value={draft.statement_md}
              onChange={(e) =>
                setDraft({ ...draft, statement_md: e.target.value })
              }
              required
            />
          </label>
          <label>
            <span>Constraints (markdown)</span>
            <textarea
              rows={3}
              value={draft.constraints_md}
              onChange={(e) =>
                setDraft({ ...draft, constraints_md: e.target.value })
              }
            />
          </label>
          <div className="question-editor__row">
            <label>
              <span>Difficulty</span>
              <select
                value={draft.difficulty}
                onChange={(e) =>
                  setDraft({ ...draft, difficulty: Number(e.target.value) })
                }
              >
                {[1, 2, 3, 4, 5].map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Time limit (ms)</span>
              <input
                type="number"
                value={draft.time_limit_ms}
                onChange={(e) =>
                  setDraft({ ...draft, time_limit_ms: Number(e.target.value) })
                }
              />
            </label>
            <label>
              <span>Memory limit (MB)</span>
              <input
                type="number"
                value={draft.memory_limit_mb}
                onChange={(e) =>
                  setDraft({ ...draft, memory_limit_mb: Number(e.target.value) })
                }
              />
            </label>
          </div>
          <label>
            <span>Topics</span>
            <select
              multiple
              size={4}
              value={draft.topic_ids}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  topic_ids: Array.from(
                    e.target.selectedOptions,
                    (option) => option.value,
                  ),
                })
              }
            >
              {(topics.data ?? []).map((topic) => (
                <option key={topic.id} value={topic.id}>
                  {topic.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Starter code (Python)</span>
            <textarea
              rows={4}
              value={draft.starter_code.python ?? ''}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  starter_code: { ...draft.starter_code, python: e.target.value },
                })
              }
            />
          </label>
          <button type="submit" className="console-button" disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>

        <aside className="question-editor__preview">
          <h2>Preview</h2>
          <div className="question-editor__markdown">
            <Markdown>{draft.statement_md || '_Nothing to preview yet._'}</Markdown>
            {draft.constraints_md && (
              <>
                <h3>Constraints</h3>
                <Markdown>{draft.constraints_md}</Markdown>
              </>
            )}
          </div>
        </aside>
      </form>

      {!isNew && (
        <section className="test-cases">
          <h2>Test cases</h2>
          <p className="test-cases__hint">
            Editing a published question creates a new version; test cases are
            copied forward automatically.
          </p>
          <table className="console-table">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Sample</th>
                <th scope="col">Input key</th>
              </tr>
            </thead>
            <tbody>
              {(testCases.data ?? []).map((testCase) => (
                <tr key={testCase.id}>
                  <td>{testCase.ordinal}</td>
                  <td>{testCase.is_sample ? 'yes' : 'no'}</td>
                  <td className="test-cases__key">{testCase.input_s3_key}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="console-form test-cases__new">
            <label>
              <span>Input</span>
              <textarea
                rows={3}
                value={tcInput}
                onChange={(e) => setTcInput(e.target.value)}
              />
            </label>
            <label>
              <span>Expected output</span>
              <textarea
                rows={3}
                value={tcExpected}
                onChange={(e) => setTcExpected(e.target.value)}
              />
            </label>
            <label className="test-cases__sample">
              <input
                type="checkbox"
                checked={tcIsSample}
                onChange={(e) => setTcIsSample(e.target.checked)}
              />
              <span>Sample case (candidates can run against it)</span>
            </label>
            <button
              type="button"
              className="console-button"
              disabled={addTestCase.isPending || !tcInput}
              onClick={() =>
                addTestCase.mutate(
                  { input: tcInput, expected: tcExpected, isSample: tcIsSample },
                  {
                    onSuccess: () => {
                      setTcInput('')
                      setTcExpected('')
                    },
                  },
                )
              }
            >
              {addTestCase.isPending ? 'Uploading…' : 'Add test case'}
            </button>
          </div>
        </section>
      )}
    </section>
  )
}
