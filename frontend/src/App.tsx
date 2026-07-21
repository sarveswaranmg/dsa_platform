import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router-dom'

import { ExamRoomPage } from './routes/ExamRoomPage'
import { InvitePage } from './routes/InvitePage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Routes>
        <Route path="/exam/invite" element={<InvitePage />} />
        <Route path="/exam/room" element={<ExamRoomPage />} />
        <Route path="*" element={<Navigate to="/exam/invite" replace />} />
      </Routes>
    </QueryClientProvider>
  )
}
