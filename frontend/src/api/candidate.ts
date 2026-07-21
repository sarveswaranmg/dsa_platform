import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'

import { apiFetch } from './client'
import {
  TERMINAL_SUBMISSION_STATUSES,
  type ExchangeResponse,
  type QuestionContent,
  type SessionResponse,
  type SubmissionResponse,
  type SubmitMode,
} from './types'

/** How often the session is refetched — this also re-anchors the countdown
 *  against the server clock and surfaces a lock that happened server-side. */
const SESSION_REFETCH_MS = 30_000
const SUBMISSION_POLL_MS = 1_500

export const queryKeys = {
  session: ['session'] as const,
  question: (ordinal: number) => ['session', 'question', ordinal] as const,
  submission: (id: string) => ['submission', id] as const,
}

export function exchangeInvite(
  inviteToken: string,
  googleIdToken: string,
): Promise<ExchangeResponse> {
  return apiFetch<ExchangeResponse>('/candidate/auth/exchange', {
    method: 'POST',
    anonymous: true,
    body: { invite_token: inviteToken, google_id_token: googleIdToken },
  })
}

export function useStartSession() {
  const queryClient = useQueryClient()
  return useMutation({
    // Idempotent server-side: also the resume path.
    mutationFn: () =>
      apiFetch<SessionResponse>('/candidate/session/start', { method: 'POST' }),
    onSuccess: (data) => queryClient.setQueryData(queryKeys.session, data),
  })
}

export function useSession(enabled = true): UseQueryResult<SessionResponse> {
  return useQuery({
    queryKey: queryKeys.session,
    queryFn: () => apiFetch<SessionResponse>('/candidate/session'),
    refetchInterval: SESSION_REFETCH_MS,
    enabled,
  })
}

export function useQuestion(
  ordinal: number | null,
): UseQueryResult<QuestionContent> {
  return useQuery({
    queryKey: queryKeys.question(ordinal ?? -1),
    queryFn: () =>
      apiFetch<QuestionContent>(`/candidate/session/questions/${ordinal}`),
    enabled: ordinal !== null,
    // Question versions are immutable, so content never goes stale.
    staleTime: Infinity,
  })
}

export function useSubmitCode(ordinal: number | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { language: string; source: string; mode: SubmitMode }) =>
      apiFetch<SubmissionResponse>(
        `/candidate/session/questions/${ordinal}/submissions`,
        { method: 'POST', body: vars },
      ),
    onSuccess: () => {
      // A submit can reveal that the session just locked.
      void queryClient.invalidateQueries({ queryKey: queryKeys.session })
    },
  })
}

/** Polls a submission until the judge reaches a terminal state. */
export function useSubmission(
  submissionId: string | null,
): UseQueryResult<SubmissionResponse> {
  return useQuery({
    queryKey: queryKeys.submission(submissionId ?? ''),
    queryFn: () =>
      apiFetch<SubmissionResponse>(`/candidate/submissions/${submissionId}`),
    enabled: submissionId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status && TERMINAL_SUBMISSION_STATUSES.includes(status)) return false
      return SUBMISSION_POLL_MS
    },
  })
}
