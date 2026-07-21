import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router-dom'

import { ExaminerAuthProvider } from './auth/ExaminerAuthContext'
import { RequireRole } from './auth/RequireRole'
import { ExamRoomPage } from './routes/ExamRoomPage'
import { InvitePage } from './routes/InvitePage'
import { BlueprintBuilderPage } from './routes/examiner/BlueprintBuilderPage'
import { ConsoleLayout } from './routes/examiner/ConsoleLayout'
import { ExamSchedulePage } from './routes/examiner/ExamSchedulePage'
import { LoginPage } from './routes/examiner/LoginPage'
import { QuestionBankPage } from './routes/examiner/QuestionBankPage'
import { QuestionEditorPage } from './routes/examiner/QuestionEditorPage'
import { ResultsPage } from './routes/examiner/ResultsPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ExaminerAuthProvider>
        <Routes>
          {/* Candidate plane */}
          <Route path="/exam/invite" element={<InvitePage />} />
          <Route path="/exam/room" element={<ExamRoomPage />} />

          {/* Examiner console — role gates mirror the backend's require_role */}
          <Route path="/console/login" element={<LoginPage />} />
          <Route
            path="/console"
            element={
              <RequireRole>
                <ConsoleLayout />
              </RequireRole>
            }
          >
            <Route index element={<Navigate to="/console/questions" replace />} />
            <Route path="questions" element={<QuestionBankPage />} />
            <Route
              path="questions/:questionId"
              element={
                <RequireRole roles={['admin', 'author']}>
                  <QuestionEditorPage />
                </RequireRole>
              }
            />
            <Route
              path="blueprints"
              element={
                <RequireRole roles={['admin', 'author']}>
                  <BlueprintBuilderPage />
                </RequireRole>
              }
            />
            <Route
              path="schedule"
              element={
                <RequireRole roles={['admin', 'author']}>
                  <ExamSchedulePage />
                </RequireRole>
              }
            />
            <Route
              path="results"
              element={
                <RequireRole roles={['admin', 'reviewer', 'proctor']}>
                  <ResultsPage />
                </RequireRole>
              }
            />
          </Route>

          <Route path="*" element={<Navigate to="/console/login" replace />} />
        </Routes>
      </ExaminerAuthProvider>
    </QueryClientProvider>
  )
}
