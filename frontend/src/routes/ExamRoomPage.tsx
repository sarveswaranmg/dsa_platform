import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import {
  queryKeys,
  useQuestion,
  useSession,
  useStartSession,
  useSubmission,
  useSubmitCode,
} from '../api/candidate'
import { connectCandidateSocket } from '../api/candidateSocket'
import { ApiError } from '../api/client'
import type { Language, SubmitMode } from '../api/types'
import { getExamToken } from '../auth/examToken'
import { CodeEditor } from '../components/CodeEditor'
import { Countdown } from '../components/Countdown'
import { QuestionNav } from '../components/QuestionNav'
import { QuestionPanel } from '../components/QuestionPanel'
import {
  RequirementsChangedBanner,
  type RequirementsChange,
} from '../components/RequirementsChangedBanner'
import { VerdictPanel } from '../components/VerdictPanel'

import './ExamRoomPage.css'

const draftKey = (ordinal: number, language: Language) =>
  `dsa.draft.${ordinal}.${language}`

export function ExamRoomPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [activeOrdinal, setActiveOrdinal] = useState<number | null>(null)
  const [language, setLanguage] = useState<Language>('python')
  const [source, setSource] = useState('')
  const [submissionId, setSubmissionId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [requirementsChange, setRequirementsChange] =
    useState<RequirementsChange | null>(null)

  const startSession = useStartSession()
  const session = useSession()
  const question = useQuestion(activeOrdinal)
  const submitCode = useSubmitCode(activeOrdinal)
  const submission = useSubmission(submissionId)

  const startMutate = startSession.mutate
  useEffect(() => {
    if (!getExamToken()) {
      navigate('/exam/invite', { replace: true })
      return
    }
    // Idempotent on the server: starts the session or resumes an existing one.
    startMutate()
  }, [navigate, startMutate])

  // Live WebSocket connection (Phase 2 Slice 6): pushes code snapshots for
  // the proctor's live view, surfaces mid-exam follow-ups and instant
  // verdict updates. Refs so the 30s snapshot timer always reads the
  // latest ordinal/source without tearing the connection down on every
  // keystroke or question switch.
  const activeOrdinalRef = useRef(activeOrdinal)
  activeOrdinalRef.current = activeOrdinal
  const sourceRef = useRef(source)
  sourceRef.current = source
  const submissionIdRef = useRef(submissionId)
  submissionIdRef.current = submissionId

  useEffect(() => {
    if (!session.data) return
    const socket = connectCandidateSocket({
      getOrdinal: () => activeOrdinalRef.current,
      getSource: () => sourceRef.current,
      onFollowupPushed: setRequirementsChange,
      onVerdict: () => {
        const currentId = submissionIdRef.current
        if (currentId) {
          void queryClient.invalidateQueries({ queryKey: queryKeys.submission(currentId) })
        }
      },
    })
    return () => socket.close()
  }, [session.data, queryClient])

  const questions = useMemo(
    () => session.data?.questions ?? [],
    [session.data?.questions],
  )

  useEffect(() => {
    if (activeOrdinal === null && questions.length > 0) {
      setActiveOrdinal(questions[0].ordinal)
    }
  }, [questions, activeOrdinal])

  // Seed the editor from the saved draft, else the question's starter code.
  useEffect(() => {
    if (activeOrdinal === null || !question.data) return
    const saved = sessionStorage.getItem(draftKey(activeOrdinal, language))
    setSource(saved ?? question.data.starter_code[language] ?? '')
  }, [activeOrdinal, language, question.data])

  const handleSourceChange = useCallback(
    (value: string) => {
      setSource(value)
      if (activeOrdinal !== null) {
        sessionStorage.setItem(draftKey(activeOrdinal, language), value)
      }
    },
    [activeOrdinal, language],
  )

  const locked = session.data?.status !== 'in_progress'

  const run = useCallback(
    (mode: SubmitMode) => {
      if (activeOrdinal === null) return
      setActionError(null)
      submitCode.mutate(
        { language, source, mode },
        {
          onSuccess: (created) => setSubmissionId(created.id),
          onError: (caught) =>
            setActionError(
              caught instanceof ApiError
                ? caught.detail
                : 'Could not reach the judge. Try again.',
            ),
        },
      )
    },
    [activeOrdinal, language, source, submitCode],
  )

  if (session.isLoading || startSession.isPending) {
    return <main className="room room--message">Preparing your exam…</main>
  }

  if (startSession.isError || session.isError) {
    const error = (startSession.error ?? session.error) as unknown
    return (
      <main className="room room--message" role="alert">
        {error instanceof ApiError
          ? error.detail
          : 'The exam could not be loaded.'}
      </main>
    )
  }

  return (
    <div className="room">
      <header className="room__header">
        <div className="room__heading">
          <h1 className="room__title">DSA Assessment</h1>
          <QuestionNav
            questions={questions}
            activeOrdinal={activeOrdinal}
            onSelect={setActiveOrdinal}
          />
        </div>
        {session.data && (
          <Countdown
            remainingSeconds={session.data.remaining_seconds}
            anchorKey={`${session.data.status}:${session.dataUpdatedAt}`}
            onExpire={() => void session.refetch()}
          />
        )}
      </header>

      <RequirementsChangedBanner
        change={requirementsChange}
        onDismiss={() => setRequirementsChange(null)}
      />

      {locked && (
        <p className="room__locked" role="alert">
          This session has ended. Your submitted work has been saved; no further
          submissions are accepted.
        </p>
      )}

      <div className="room__body">
        <div className="room__left">
          {question.data ? (
            <QuestionPanel question={question.data} />
          ) : (
            <p className="room__placeholder">Loading question…</p>
          )}
        </div>
        <div className="room__right">
          <CodeEditor
            language={language}
            source={source}
            disabled={locked}
            busy={submitCode.isPending}
            onLanguageChange={setLanguage}
            onSourceChange={handleSourceChange}
            onRun={() => run('run')}
            onSubmit={() => run('submit')}
          />
          {actionError && (
            <p className="room__error" role="alert">
              {actionError}
            </p>
          )}
          <VerdictPanel
            submission={submission.data ?? null}
            pending={submitCode.isPending}
          />
        </div>
      </div>
    </div>
  )
}
