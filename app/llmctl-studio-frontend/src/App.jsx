import { Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import OverviewPage from './pages/OverviewPage'
import ApiDiagnosticsPage from './pages/ApiDiagnosticsPage'
import ChatActivityPage from './pages/ChatActivityPage'
import ChatThreadPage from './pages/ChatThreadPage'
import ExecutionMonitorPage from './pages/ExecutionMonitorPage'
import AgentsPage from './pages/AgentsPage'
import AgentDetailPage from './pages/AgentDetailPage'
import AgentEditPage from './pages/AgentEditPage'
import AgentNewPage from './pages/AgentNewPage'
import RunsPage from './pages/RunsPage'
import RunDetailPage from './pages/RunDetailPage'
import RunEditPage from './pages/RunEditPage'
import RunNewPage from './pages/RunNewPage'
import NodesPage from './pages/NodesPage'
import NodeDetailPage from './pages/NodeDetailPage'
import NodeNewPage from './pages/NodeNewPage'
import QuickTaskPage from './pages/QuickTaskPage'
import PlansPage from './pages/PlansPage'
import PlanDetailPage from './pages/PlanDetailPage'
import PlanEditPage from './pages/PlanEditPage'
import PlanNewPage from './pages/PlanNewPage'
import MilestonesPage from './pages/MilestonesPage'
import MilestoneDetailPage from './pages/MilestoneDetailPage'
import MilestoneEditPage from './pages/MilestoneEditPage'
import MilestoneNewPage from './pages/MilestoneNewPage'
import MemoriesPage from './pages/MemoriesPage'
import MemoryDetailPage from './pages/MemoryDetailPage'
import MemoryEditPage from './pages/MemoryEditPage'
import MemoryNewPage from './pages/MemoryNewPage'
import TaskTemplatesPage from './pages/TaskTemplatesPage'
import TaskTemplateDetailPage from './pages/TaskTemplateDetailPage'
import TaskTemplateEditPage from './pages/TaskTemplateEditPage'
import TaskTemplateNewPage from './pages/TaskTemplateNewPage'
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
      <Route path="/agents" element={<AppLayout><AgentsPage /></AppLayout>} />
      <Route path="/agents/new" element={<AppLayout><AgentNewPage /></AppLayout>} />
      <Route path="/agents/:agentId" element={<AppLayout><AgentDetailPage /></AppLayout>} />
      <Route path="/agents/:agentId/edit" element={<AppLayout><AgentEditPage /></AppLayout>} />
      <Route path="/runs" element={<AppLayout><RunsPage /></AppLayout>} />
      <Route path="/runs/new" element={<AppLayout><RunNewPage /></AppLayout>} />
      <Route path="/runs/:runId" element={<AppLayout><RunDetailPage /></AppLayout>} />
      <Route path="/runs/:runId/edit" element={<AppLayout><RunEditPage /></AppLayout>} />
      <Route path="/quick" element={<AppLayout><QuickTaskPage /></AppLayout>} />
      <Route path="/nodes" element={<AppLayout><NodesPage /></AppLayout>} />
      <Route path="/nodes/new" element={<AppLayout><NodeNewPage /></AppLayout>} />
      <Route path="/nodes/:nodeId" element={<AppLayout><NodeDetailPage /></AppLayout>} />
      <Route path="/plans" element={<AppLayout><PlansPage /></AppLayout>} />
      <Route path="/plans/new" element={<AppLayout><PlanNewPage /></AppLayout>} />
      <Route path="/plans/:planId" element={<AppLayout><PlanDetailPage /></AppLayout>} />
      <Route path="/plans/:planId/edit" element={<AppLayout><PlanEditPage /></AppLayout>} />
      <Route path="/milestones" element={<AppLayout><MilestonesPage /></AppLayout>} />
      <Route path="/milestones/new" element={<AppLayout><MilestoneNewPage /></AppLayout>} />
      <Route path="/milestones/:milestoneId" element={<AppLayout><MilestoneDetailPage /></AppLayout>} />
      <Route path="/milestones/:milestoneId/edit" element={<AppLayout><MilestoneEditPage /></AppLayout>} />
      <Route path="/memories" element={<AppLayout><MemoriesPage /></AppLayout>} />
      <Route path="/memories/new" element={<AppLayout><MemoryNewPage /></AppLayout>} />
      <Route path="/memories/:memoryId" element={<AppLayout><MemoryDetailPage /></AppLayout>} />
      <Route path="/memories/:memoryId/edit" element={<AppLayout><MemoryEditPage /></AppLayout>} />
      <Route path="/task-templates" element={<AppLayout><TaskTemplatesPage /></AppLayout>} />
      <Route path="/task-templates/new" element={<AppLayout><TaskTemplateNewPage /></AppLayout>} />
      <Route path="/task-templates/:templateId" element={<AppLayout><TaskTemplateDetailPage /></AppLayout>} />
      <Route path="/task-templates/:templateId/edit" element={<AppLayout><TaskTemplateEditPage /></AppLayout>} />
      <Route path="/overview" element={<LegacyMirrorPage />} />
      <Route path="*" element={<LegacyMirrorPage />} />
    </Routes>
  )
}
