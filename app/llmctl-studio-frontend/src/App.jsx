import { Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import OverviewPage from './pages/OverviewPage'
import ApiDiagnosticsPage from './pages/ApiDiagnosticsPage'
import ChatActivityPage from './pages/ChatActivityPage'
import ChatThreadPage from './pages/ChatThreadPage'
import NotFoundPage from './pages/NotFoundPage'
import ParityChecklistPage from './pages/ParityChecklistPage'

export default function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/parity-checklist" element={<ParityChecklistPage />} />
        <Route path="/chat/activity" element={<ChatActivityPage />} />
        <Route path="/chat/threads/:threadId" element={<ChatThreadPage />} />
        <Route path="/api-diagnostics" element={<ApiDiagnosticsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </AppLayout>
  )
}
