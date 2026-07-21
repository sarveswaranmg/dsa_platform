import type { CaseVerdict, Language, Verdict } from '../types'

export type ExaminerRole = 'admin' | 'author' | 'proctor' | 'reviewer'
export type QuestionStatus = 'draft' | 'published' | 'archived'

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface Examiner {
  id: string
  org_id: string
  email: string
  role: ExaminerRole
  totp_enabled: boolean
  is_active: boolean
  created_at: string
}

export interface Topic {
  id: string
  org_id: string
  name: string
  parent_id: string | null
  created_at: string
}

export interface QuestionVersion {
  id: string
  question_id: string
  version_number: number
  title: string
  statement_md: string
  constraints_md: string
  difficulty: number
  time_limit_ms: number
  memory_limit_mb: number
  starter_code: Partial<Record<Language, string>>
  created_at: string
}

export interface Question {
  id: string
  org_id: string
  status: QuestionStatus
  published_version_id: string | null
  current_version: QuestionVersion
  topic_ids: string[]
}

export interface QuestionListItem {
  id: string
  status: QuestionStatus
  title: string
  difficulty: number
  version_number: number
}

export interface QuestionPayload {
  title: string
  statement_md: string
  constraints_md: string
  difficulty: number
  time_limit_ms: number
  memory_limit_mb: number
  starter_code: Partial<Record<Language, string>>
  topic_ids: string[]
}

export interface TestCase {
  id: string
  question_version_id: string
  ordinal: number
  is_sample: boolean
  input_s3_key: string
  expected_output_s3_key: string
  created_at: string
}

export interface TestCaseCreated extends TestCase {
  upload_input_url: string
  upload_output_url: string
}

export interface TestCaseDownload extends TestCase {
  input_url: string
  output_url: string
}

export interface TopicMixEntry {
  topic_id: string
  weight: number
  difficulty_min: number
  difficulty_max: number
  question_count: number
}

export interface BlueprintVersion {
  id: string
  blueprint_id: string
  version_number: number
  target_role: string
  experience_band: string
  total_duration_minutes: number
  topic_mix: TopicMixEntry[]
  created_at: string
}

export interface Blueprint {
  id: string
  org_id: string
  name: string
  current_version: BlueprintVersion
}

export interface BlueprintPayload {
  name: string
  target_role: string
  experience_band: string
  total_duration_minutes: number
  topic_mix: TopicMixEntry[]
}

export interface Exam {
  id: string
  org_id: string
  blueprint_id: string
  blueprint_version_id: string
  candidate_email: string
  starts_at: string
  ends_at: string
  status: string
}

export interface ExamScheduled extends Exam {
  invite: { id: string; status: string; candidate_email: string; consumed_at: string | null } | null
  invite_link: string | null
}

export interface SubmissionSummary {
  id: string
  question_version_id: string
  session_id: string | null
  language: string
  mode: 'run' | 'submit'
  status: string
  summary_verdict: Verdict | null
  created_at: string
}

export interface SubmissionDetail extends SubmissionSummary {
  exam_id: string
  source: string
  compile_error: string | null
  cases: CaseVerdict[]
}
