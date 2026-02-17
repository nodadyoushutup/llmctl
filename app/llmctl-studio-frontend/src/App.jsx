import { Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import OverviewPage from './pages/OverviewPage'
import ApiDiagnosticsPage from './pages/ApiDiagnosticsPage'
import ChatActivityPage from './pages/ChatActivityPage'
import ChatThreadPage from './pages/ChatThreadPage'
import ExecutionMonitorPage from './pages/ExecutionMonitorPage'
import LegacyMirrorPage from './pages/LegacyMirrorPage'
import ParityChecklistPage from './pages/ParityChecklistPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/overview" replace />} />
      <Route path="/migration" element={<AppLayout><OverviewPage /></AppLayout>} />
      <Route path="/parity-checklist" element={<AppLayout><ParityChecklistPage /></AppLayout>} />
      <Route path="/chat/activity" element={<AppLayout><ChatActivityPage /></AppLayout>} />
      <Route path="/chat/threads/:threadId" element={<AppLayout><ChatThreadPage /></AppLayout>} />
      <Route path="/execution-monitor" element={<AppLayout><ExecutionMonitorPage /></AppLayout>} />
      <Route path="/api-diagnostics" element={<AppLayout><ApiDiagnosticsPage /></AppLayout>} />
      <Route path="*" element={<LegacyMirrorPage />} />
    </Routes>
  )
}
