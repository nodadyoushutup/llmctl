import { Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import OverviewPage from './pages/OverviewPage'
import ApiDiagnosticsPage from './pages/ApiDiagnosticsPage'
import ChatPage from './pages/ChatPage'
import ChatActivityPage from './pages/ChatActivityPage'
import ChatThreadRedirectPage from './pages/ChatThreadRedirectPage'
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
import FlowchartsPage from './pages/FlowchartsPage'
import FlowchartNewPage from './pages/FlowchartNewPage'
import FlowchartDetailPage from './pages/FlowchartDetailPage'
import FlowchartEditPage from './pages/FlowchartEditPage'
import FlowchartHistoryPage from './pages/FlowchartHistoryPage'
import FlowchartRunDetailPage from './pages/FlowchartRunDetailPage'
import SettingsCorePage from './pages/SettingsCorePage'
import SettingsProviderPage from './pages/SettingsProviderPage'
import SettingsRuntimePage from './pages/SettingsRuntimePage'
import SettingsChatPage from './pages/SettingsChatPage'
import SettingsIntegrationsPage from './pages/SettingsIntegrationsPage'
import SkillsPage from './pages/SkillsPage'
import SkillNewPage from './pages/SkillNewPage'
import SkillImportPage from './pages/SkillImportPage'
import SkillDetailPage from './pages/SkillDetailPage'
import SkillEditPage from './pages/SkillEditPage'
import ScriptsPage from './pages/ScriptsPage'
import ScriptNewPage from './pages/ScriptNewPage'
import ScriptDetailPage from './pages/ScriptDetailPage'
import ScriptEditPage from './pages/ScriptEditPage'
import AttachmentsPage from './pages/AttachmentsPage'
import AttachmentDetailPage from './pages/AttachmentDetailPage'
import ModelsPage from './pages/ModelsPage'
import ModelNewPage from './pages/ModelNewPage'
import ModelDetailPage from './pages/ModelDetailPage'
import ModelEditPage from './pages/ModelEditPage'
import McpsPage from './pages/McpsPage'
import McpNewPage from './pages/McpNewPage'
import McpDetailPage from './pages/McpDetailPage'
import McpEditPage from './pages/McpEditPage'
import GithubPage from './pages/GithubPage'
import GithubPullRequestPage from './pages/GithubPullRequestPage'
import JiraPage from './pages/JiraPage'
import JiraIssuePage from './pages/JiraIssuePage'
import ConfluencePage from './pages/ConfluencePage'
import ChromaCollectionsPage from './pages/ChromaCollectionsPage'
import ChromaCollectionDetailPage from './pages/ChromaCollectionDetailPage'
import RagChatPage from './pages/RagChatPage'
import RagSourcesPage from './pages/RagSourcesPage'
import RagSourceNewPage from './pages/RagSourceNewPage'
import RagSourceDetailPage from './pages/RagSourceDetailPage'
import RagSourceEditPage from './pages/RagSourceEditPage'
import ParityChecklistPage from './pages/ParityChecklistPage'
import NotFoundPage from './pages/NotFoundPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/overview" replace />} />
      <Route path="/migration" element={<AppLayout><OverviewPage /></AppLayout>} />
      <Route path="/parity-checklist" element={<AppLayout><ParityChecklistPage /></AppLayout>} />
      <Route path="/chat" element={<AppLayout><ChatPage /></AppLayout>} />
      <Route path="/chat/activity" element={<AppLayout><ChatActivityPage /></AppLayout>} />
      <Route path="/chat/threads/:threadId" element={<AppLayout><ChatThreadRedirectPage /></AppLayout>} />
      <Route path="/monitor" element={<Navigate to="/execution-monitor" replace />} />
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
      <Route path="/flowcharts" element={<AppLayout><FlowchartsPage /></AppLayout>} />
      <Route path="/flowcharts/new" element={<AppLayout><FlowchartNewPage /></AppLayout>} />
      <Route path="/flowcharts/:flowchartId" element={<AppLayout><FlowchartDetailPage /></AppLayout>} />
      <Route path="/flowcharts/:flowchartId/edit" element={<AppLayout><FlowchartEditPage /></AppLayout>} />
      <Route path="/flowcharts/:flowchartId/history" element={<AppLayout><FlowchartHistoryPage /></AppLayout>} />
      <Route path="/flowcharts/:flowchartId/history/:runId" element={<AppLayout><FlowchartRunDetailPage /></AppLayout>} />
      <Route path="/flowcharts/runs/:runId" element={<AppLayout><FlowchartRunDetailPage /></AppLayout>} />
      <Route path="/settings/core" element={<AppLayout><SettingsCorePage /></AppLayout>} />
      <Route path="/settings/provider" element={<AppLayout><SettingsProviderPage /></AppLayout>} />
      <Route path="/settings/provider/:section" element={<AppLayout><SettingsProviderPage /></AppLayout>} />
      <Route path="/settings/runtime" element={<AppLayout><SettingsRuntimePage /></AppLayout>} />
      <Route path="/settings/runtime/:section" element={<AppLayout><SettingsRuntimePage /></AppLayout>} />
      <Route path="/settings/chat" element={<AppLayout><SettingsChatPage /></AppLayout>} />
      <Route path="/settings/integrations" element={<AppLayout><SettingsIntegrationsPage /></AppLayout>} />
      <Route path="/settings/integrations/:section" element={<AppLayout><SettingsIntegrationsPage /></AppLayout>} />
      <Route path="/skills" element={<AppLayout><SkillsPage /></AppLayout>} />
      <Route path="/skills/new" element={<AppLayout><SkillNewPage /></AppLayout>} />
      <Route path="/skills/import" element={<AppLayout><SkillImportPage /></AppLayout>} />
      <Route path="/skills/:skillId" element={<AppLayout><SkillDetailPage /></AppLayout>} />
      <Route path="/skills/:skillId/edit" element={<AppLayout><SkillEditPage /></AppLayout>} />
      <Route path="/scripts" element={<AppLayout><ScriptsPage /></AppLayout>} />
      <Route path="/scripts/new" element={<AppLayout><ScriptNewPage /></AppLayout>} />
      <Route path="/scripts/:scriptId" element={<AppLayout><ScriptDetailPage /></AppLayout>} />
      <Route path="/scripts/:scriptId/edit" element={<AppLayout><ScriptEditPage /></AppLayout>} />
      <Route path="/attachments" element={<AppLayout><AttachmentsPage /></AppLayout>} />
      <Route path="/attachments/:attachmentId" element={<AppLayout><AttachmentDetailPage /></AppLayout>} />
      <Route path="/models" element={<AppLayout><ModelsPage /></AppLayout>} />
      <Route path="/models/new" element={<AppLayout><ModelNewPage /></AppLayout>} />
      <Route path="/models/:modelId" element={<AppLayout><ModelDetailPage /></AppLayout>} />
      <Route path="/models/:modelId/edit" element={<AppLayout><ModelEditPage /></AppLayout>} />
      <Route path="/mcps" element={<AppLayout><McpsPage /></AppLayout>} />
      <Route path="/mcps/new" element={<AppLayout><McpNewPage /></AppLayout>} />
      <Route path="/mcps/:mcpId" element={<AppLayout><McpDetailPage /></AppLayout>} />
      <Route path="/mcps/:mcpId/edit" element={<AppLayout><McpEditPage /></AppLayout>} />
      <Route path="/github" element={<AppLayout><GithubPage /></AppLayout>} />
      <Route path="/github/pulls/:prNumber" element={<AppLayout><GithubPullRequestPage /></AppLayout>} />
      <Route path="/github/pulls/:prNumber/commits" element={<AppLayout><GithubPullRequestPage /></AppLayout>} />
      <Route path="/github/pulls/:prNumber/checks" element={<AppLayout><GithubPullRequestPage /></AppLayout>} />
      <Route path="/github/pulls/:prNumber/files" element={<AppLayout><GithubPullRequestPage /></AppLayout>} />
      <Route path="/jira" element={<AppLayout><JiraPage /></AppLayout>} />
      <Route path="/jira/issues/:issueKey" element={<AppLayout><JiraIssuePage /></AppLayout>} />
      <Route path="/confluence" element={<AppLayout><ConfluencePage /></AppLayout>} />
      <Route path="/chroma" element={<Navigate to="/chroma/collections" replace />} />
      <Route path="/chroma/collections" element={<AppLayout><ChromaCollectionsPage /></AppLayout>} />
      <Route path="/chroma/collections/detail" element={<AppLayout><ChromaCollectionDetailPage /></AppLayout>} />
      <Route path="/rag/chat" element={<AppLayout><RagChatPage /></AppLayout>} />
      <Route path="/rag/sources" element={<AppLayout><RagSourcesPage /></AppLayout>} />
      <Route path="/rag/sources/new" element={<AppLayout><RagSourceNewPage /></AppLayout>} />
      <Route path="/rag/sources/:sourceId" element={<AppLayout><RagSourceDetailPage /></AppLayout>} />
      <Route path="/rag/sources/:sourceId/edit" element={<AppLayout><RagSourceEditPage /></AppLayout>} />
      <Route path="/overview" element={<AppLayout><OverviewPage /></AppLayout>} />
      <Route path="*" element={<AppLayout><NotFoundPage /></AppLayout>} />
    </Routes>
  )
}
