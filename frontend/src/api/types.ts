// Mirrors the exam service's candidate-plane schemas
// (services/exam/app/schemas/{candidate,session,submission}.py).

export type Verdict = 'AC' | 'WA' | 'TLE' | 'MLE' | 'RE' | 'CE'
export type Language = 'python' | 'java' | 'cpp'
export type SubmitMode = 'run' | 'submit'
export type SessionStatus = 'in_progress' | 'submitted' | 'expired'
export type SubmissionStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'compile_error'
  | 'error'

export const LANGUAGES: readonly Language[] = ['python', 'java', 'cpp']

export interface ExchangeResponse {
  exam_token: string
  token_type: string
  exam_id: string
  candidate_email: string
  starts_at: string
  ends_at: string
}

export interface AssignedQuestion {
  ordinal: number
  question_id: string
  question_version_id: string
}

export interface SessionResponse {
  id: string
  exam_id: string
  status: SessionStatus
  started_at: string
  deadline_at: string
  /** Server-computed; the client never trusts its own wall clock. */
  remaining_seconds: number
  questions: AssignedQuestion[]
}

export interface QuestionContent {
  ordinal: number
  question_id: string
  question_version_id: string
  title: string
  statement_md: string
  constraints_md: string
  difficulty: number
  time_limit_ms: number
  memory_limit_mb: number
  starter_code: Partial<Record<Language, string>>
}

export interface CaseVerdict {
  ordinal: number
  verdict: Verdict
  runtime_ms: number
  memory_kb: number
}

export interface SubmissionResponse {
  id: string
  exam_id: string
  question_version_id: string
  language: string
  mode: SubmitMode
  status: SubmissionStatus
  summary_verdict: Verdict | null
  compile_error: string | null
  cases: CaseVerdict[]
}

export const TERMINAL_SUBMISSION_STATUSES: readonly SubmissionStatus[] = [
  'completed',
  'compile_error',
  'error',
]
