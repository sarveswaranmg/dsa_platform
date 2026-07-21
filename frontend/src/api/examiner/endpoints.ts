import { examinerFetch } from './client'
import type {
  Blueprint,
  BlueprintPayload,
  Exam,
  ExamScheduled,
  Examiner,
  Question,
  QuestionListItem,
  QuestionPayload,
  SubmissionDetail,
  SubmissionSummary,
  TestCaseCreated,
  TestCaseDownload,
  TokenResponse,
  Topic,
} from './types'

// --- auth (exam service) ---

export function login(
  email: string,
  password: string,
  totpCode: string,
): Promise<TokenResponse> {
  return examinerFetch<TokenResponse>('/auth/login', {
    method: 'POST',
    anonymous: true,
    body: { email, password, totp_code: totpCode },
  })
}

export function logout(refreshToken: string): Promise<void> {
  return examinerFetch<void>('/auth/logout', {
    method: 'POST',
    anonymous: true,
    body: { refresh_token: refreshToken },
  })
}

export function fetchMe(): Promise<Examiner> {
  return examinerFetch<Examiner>('/examiners/me')
}

// --- taxonomy + questions (question service) ---

export function listTopics(): Promise<Topic[]> {
  return examinerFetch<Topic[]>('/topics')
}

export function createTopic(name: string, parentId: string | null): Promise<Topic> {
  return examinerFetch<Topic>('/topics', {
    method: 'POST',
    body: { name, parent_id: parentId },
  })
}

export function listQuestions(filters: {
  topicId?: string
  difficulty?: number
  status?: string
}): Promise<QuestionListItem[]> {
  const params = new URLSearchParams()
  if (filters.topicId) params.set('topic_id', filters.topicId)
  if (filters.difficulty) params.set('difficulty', String(filters.difficulty))
  if (filters.status) params.set('status', filters.status)
  const query = params.toString()
  return examinerFetch<QuestionListItem[]>(
    `/questions${query ? `?${query}` : ''}`,
  )
}

export function getQuestion(id: string): Promise<Question> {
  return examinerFetch<Question>(`/questions/${id}`)
}

export function createQuestion(payload: QuestionPayload): Promise<Question> {
  return examinerFetch<Question>('/questions', { method: 'POST', body: payload })
}

export function updateQuestion(
  id: string,
  payload: Partial<QuestionPayload>,
): Promise<Question> {
  return examinerFetch<Question>(`/questions/${id}`, {
    method: 'PATCH',
    body: payload,
  })
}

export function publishQuestion(id: string): Promise<Question> {
  return examinerFetch<Question>(`/questions/${id}/publish`, { method: 'POST' })
}

export function listTestCases(questionId: string): Promise<TestCaseDownload[]> {
  return examinerFetch<TestCaseDownload[]>(`/questions/${questionId}/test-cases`)
}

export function createTestCase(
  questionId: string,
  isSample: boolean,
): Promise<TestCaseCreated> {
  return examinerFetch<TestCaseCreated>(`/questions/${questionId}/test-cases`, {
    method: 'POST',
    body: { is_sample: isSample },
  })
}

export function deleteTestCase(
  questionId: string,
  testCaseId: string,
): Promise<void> {
  return examinerFetch<void>(
    `/questions/${questionId}/test-cases/${testCaseId}`,
    { method: 'DELETE' },
  )
}

/** Uploads straight to S3 via the presigned URL — file bytes never touch the API. */
export async function uploadToPresignedUrl(
  url: string,
  content: string,
): Promise<void> {
  const response = await fetch(url, { method: 'PUT', body: content })
  if (!response.ok) {
    throw new Error(`Upload failed (${response.status})`)
  }
}

// --- blueprints + exams (exam service) ---

export function listBlueprints(): Promise<Blueprint[]> {
  return examinerFetch<Blueprint[]>('/blueprints')
}

export function createBlueprint(payload: BlueprintPayload): Promise<Blueprint> {
  return examinerFetch<Blueprint>('/blueprints', {
    method: 'POST',
    body: payload,
  })
}

export function listExams(): Promise<Exam[]> {
  return examinerFetch<Exam[]>('/exams')
}

export function scheduleExam(payload: {
  candidate_email: string
  blueprint_id: string
  starts_at: string
  ends_at: string
}): Promise<ExamScheduled> {
  return examinerFetch<ExamScheduled>('/exams', { method: 'POST', body: payload })
}

// --- results (exam service) ---

export function listExamSubmissions(
  examId: string,
): Promise<SubmissionSummary[]> {
  return examinerFetch<SubmissionSummary[]>(`/exams/${examId}/submissions`)
}

export function getSubmissionDetail(id: string): Promise<SubmissionDetail> {
  return examinerFetch<SubmissionDetail>(`/submissions/${id}`)
}
