export const parityStatusLabels = {
  migrated: 'Native React',
  pending: 'Needs Migration',
}

export const parityChecklist = [
  {
    wave: 'Wave 1',
    area: 'Core Shell',
    legacyPath: '/overview',
    reactPath: '/overview',
    status: 'migrated',
    notes: 'React shell and runtime wiring are active.',
  },
  {
    wave: 'Wave 1',
    area: 'API Diagnostics',
    legacyPath: '/api/health + /api/chat/activity',
    reactPath: '/api-diagnostics',
    status: 'migrated',
    notes: 'Connectivity checks for split frontend/backend pathing.',
  },
  {
    wave: 'Wave 1',
    area: 'Chat Activity',
    legacyPath: '/chat/activity',
    reactPath: '/chat/activity',
    status: 'migrated',
    notes: 'Reads from /api/chat/activity.',
  },
  {
    wave: 'Wave 1',
    area: 'Chat Thread Detail',
    legacyPath: '/chat',
    reactPath: '/chat/threads/:threadId',
    status: 'migrated',
    notes: 'Reads from /api/chat/threads/:threadId.',
  },
  {
    wave: 'Wave 2',
    area: 'Agents',
    legacyPath: '/agents',
    reactPath: '/agents',
    status: 'migrated',
    notes: 'Native React list/detail/new/edit with priority and skill binding operations.',
  },
  {
    wave: 'Wave 2',
    area: 'Runs',
    legacyPath: '/runs',
    reactPath: '/runs + /runs/:runId + /runs/new + /runs/:runId/edit',
    status: 'migrated',
    notes: 'Native React list/detail/policy/edit metadata coverage with autorun actions.',
  },
  {
    wave: 'Wave 2',
    area: 'Quick Tasks + Nodes',
    legacyPath: '/quick and /nodes',
    reactPath: '/quick + /nodes + /nodes/new + /nodes/:nodeId',
    status: 'migrated',
    notes: 'Native React quick task submit, nodes list filters/actions, and node detail lifecycle polling.',
  },
  {
    wave: 'Wave 3',
    area: 'Plans',
    legacyPath: '/plans',
    reactPath: '/plans + /plans/:planId + /plans/:planId/edit',
    status: 'migrated',
    notes: 'Native React list/detail/edit with stage/task mutations.',
  },
  {
    wave: 'Wave 3',
    area: 'Milestones',
    legacyPath: '/milestones',
    reactPath: '/milestones + /milestones/:milestoneId + /milestones/:milestoneId/edit',
    status: 'migrated',
    notes: 'Native React list/detail/edit with status/priority/health updates.',
  },
  {
    wave: 'Wave 3',
    area: 'Task Templates',
    legacyPath: '/task-templates',
    reactPath: '/task-templates + /task-templates/:templateId + /task-templates/:templateId/edit',
    status: 'migrated',
    notes: 'Native React workflow-node list plus task-template detail/edit/delete flows.',
  },
  {
    wave: 'Wave 3',
    area: 'Memories',
    legacyPath: '/memories',
    reactPath: '/memories + /memories/:memoryId + /memories/:memoryId/edit',
    status: 'migrated',
    notes: 'Native React list/detail/edit/delete and flowchart-managed create policy.',
  },
  {
    wave: 'Wave 4',
    area: 'Flowcharts',
    legacyPath: '/flowcharts',
    reactPath:
      '/flowcharts + /flowcharts/new + /flowcharts/:flowchartId + /flowcharts/:flowchartId/edit + /flowcharts/:flowchartId/history + /flowcharts/:flowchartId/history/:runId + /flowcharts/runs/:runId',
    status: 'migrated',
    notes: 'Native React coverage for list/new/detail/edit/history/run-detail with graph and node utility mutations.',
  },
  {
    wave: 'Wave 5',
    area: 'Skills',
    legacyPath: '/skills',
    reactPath: '/skills + /skills/new + /skills/import + /skills/:skillId + /skills/:skillId/edit',
    status: 'migrated',
    notes: 'Native React list/detail/new/edit/import flows with API-backed CRUD and export link support.',
  },
  {
    wave: 'Wave 5',
    area: 'Scripts',
    legacyPath: '/scripts',
    reactPath: '/scripts + /scripts/new + /scripts/:scriptId + /scripts/:scriptId/edit',
    status: 'migrated',
    notes: 'Native React list/detail/new/edit flows with API-backed create/update/delete.',
  },
  {
    wave: 'Wave 5',
    area: 'Attachments',
    legacyPath: '/attachments',
    reactPath: '/attachments + /attachments/:attachmentId',
    status: 'migrated',
    notes: 'Native React list/detail coverage with file preview/download and delete controls.',
  },
  {
    wave: 'Wave 5',
    area: 'Models',
    legacyPath: '/models',
    reactPath: '/models + /models/new + /models/:modelId + /models/:modelId/edit',
    status: 'migrated',
    notes: 'Native React list/detail/new/edit with default-model toggle and delete coverage.',
  },
  {
    wave: 'Wave 5',
    area: 'MCP Servers',
    legacyPath: '/mcps',
    reactPath: '/mcps + /mcps/new + /mcps/:mcpId + /mcps/:mcpId/edit',
    status: 'migrated',
    notes: 'Native React custom/integrated MCP list plus detail/create/edit/delete for custom servers.',
  },
  {
    wave: 'Wave 6',
    area: 'Settings Core + Provider',
    legacyPath: '/settings/core and /settings/provider',
    reactPath: '/settings/core and /settings/provider',
    status: 'migrated',
    notes: 'Native React settings core/provider pages with JSON-backed updates.',
  },
  {
    wave: 'Wave 6',
    area: 'Settings Runtime + Chat',
    legacyPath: '/settings/runtime and /settings/chat',
    reactPath: '/settings/runtime and /settings/chat',
    status: 'migrated',
    notes: 'Native React runtime/chat settings with node executor and budget controls.',
  },
  {
    wave: 'Wave 6',
    area: 'Integrations',
    legacyPath: '/settings/integrations/*',
    reactPath: '/settings/integrations/*',
    status: 'migrated',
    notes: 'Native React integrations sections for Git, GitHub, Jira, Confluence, Google, Hugging Face, and Chroma.',
  },
  {
    wave: 'Wave 7',
    area: 'External Tools',
    legacyPath: '/github, /jira, /confluence, /chroma',
    reactPath:
      '/github + /github/pulls/:prNumber + /jira + /jira/issues/:issueKey + /confluence + /chroma/collections + /chroma/collections/detail',
    status: 'migrated',
    notes: 'Native React workspace/detail coverage with API-mode JSON payloads from backend tool routes.',
  },
  {
    wave: 'Wave 7',
    area: 'RAG Pages',
    legacyPath: '/rag/chat and /rag/sources*',
    reactPath: '/rag/chat + /rag/sources + /rag/sources/new + /rag/sources/:sourceId + /rag/sources/:sourceId/edit',
    status: 'migrated',
    notes: 'Native React chat and source CRUD/quick-index flows via `/api/rag/*` endpoints.',
  },
]

export function buildParitySummary(items) {
  return items.reduce(
    (summary, item) => {
      const status = item.status === 'migrated' ? 'migrated' : 'pending'
      summary.total += 1
      summary[status] = (summary[status] || 0) + 1
      return summary
    },
    {
      total: 0,
      migrated: 0,
      pending: 0,
    },
  )
}
