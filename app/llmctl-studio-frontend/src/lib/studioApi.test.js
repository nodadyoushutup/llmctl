import { beforeEach, describe, expect, test, vi } from 'vitest'

vi.mock('./httpClient', () => ({
  requestJson: vi.fn(),
}))

import { requestJson } from './httpClient'
import {
  attachAgentSkill,
  attachFlowchartNodeMcp,
  attachFlowchartNodeScript,
  attachFlowchartNodeSkill,
  archiveChatThread,
  cancelFlowchartRun,
  cancelNode,
  createAgent,
  createAgentPriority,
  createFlowchart,
  createChatThread,
  createNode,
  createPlanStage,
  createPlanTask,
  createQuickTask,
  clearChatThread,
  deleteAgent,
  deleteAgentPriority,
  deleteMemory,
  deleteNode,
  deleteMilestone,
  deleteFlowchart,
  deletePlan,
  deletePlanStage,
  deletePlanTask,
  deleteRun,
  deleteTaskTemplate,
  detachAgentSkill,
  detachFlowchartNodeMcp,
  detachFlowchartNodeScript,
  detachFlowchartNodeSkill,
  getAgent,
  getAgentMeta,
  getAgents,
  getBackendHealth,
  getChatActivity,
  getChatRuntime,
  getChatThread,
  getAttachment,
  getAttachments,
  getMemory,
  getMemoryEdit,
  getMemoryMeta,
  getMemories,
  getMcp,
  getMcpEdit,
  getMcpMeta,
  getMcps,
  getModel,
  getModelEdit,
  getModelMeta,
  getModels,
  getGithubWorkspace,
  getGithubPullRequest,
  runGithubPullRequestCodeReview,
  getJiraWorkspace,
  getJiraIssue,
  getConfluenceWorkspace,
  getChromaCollections,
  getChromaCollection,
  deleteChromaCollection,
  getRagSources,
  getRagSourceMeta,
  createRagSource,
  getRagSource,
  getRagSourceEdit,
  updateRagSource,
  deleteRagSource,
  quickIndexRagSource,
  quickDeltaIndexRagSource,
  getRagSourceStatus,
  getSettingsChat,
  getSettingsCore,
  getSettingsIntegrations,
  getSettingsProvider,
  getSettingsRuntime,
  getMilestone,
  getMilestoneEdit,
  getMilestoneMeta,
  getMilestones,
  getFlowchart,
  getFlowchartEdit,
  getFlowchartGraph,
  getFlowchartHistory,
  getFlowchartHistoryRun,
  getFlowchartMeta,
  getFlowchartNodeUtilities,
  getFlowchartRun,
  getFlowchartRunStatus,
  getFlowcharts,
  getFlowchartRuntime,
  getNode,
  getNodeMeta,
  getNodes,
  getNodeStatus,
  getPlan,
  getPlanEdit,
  getPlanMeta,
  getPlans,
  getQuickTaskMeta,
  getRun,
  getRunEdit,
  getRunMeta,
  getRuns,
  getScript,
  getScriptEdit,
  getScriptMeta,
  getScripts,
  getSkill,
  getSkillEdit,
  getSkillImportMeta,
  getSkillMeta,
  getSkills,
  getTaskTemplate,
  getTaskTemplateEdit,
  getTaskTemplateMeta,
  getTaskTemplates,
  importSkillBundle,
  moveAgentPriority,
  moveAgentSkill,
  previewSkillImport,
  reorderFlowchartNodeScripts,
  reorderFlowchartNodeSkills,
  removeNodeAttachment,
  removeTaskTemplateAttachment,
  runFlowchart,
  setFlowchartNodeModel,
  startAgent,
  stopAgent,
  sendChatTurn,
  createMcp,
  createModel,
  createScript,
  createSkill,
  deleteAttachment,
  updateSettingsChatDefaults,
  updateSettingsIntegrationsChroma,
  updateSettingsIntegrationsConfluence,
  updateSettingsIntegrationsGit,
  updateSettingsIntegrationsGithub,
  updateSettingsIntegrationsGoogleCloud,
  updateSettingsIntegrationsGoogleWorkspace,
  updateSettingsIntegrationsHuggingface,
  updateSettingsIntegrationsJira,
  updateSettingsProviderClaude,
  updateSettingsProviderCodex,
  updateSettingsProviderControls,
  updateSettingsProviderGemini,
  updateSettingsProviderVllmLocal,
  updateSettingsProviderVllmRemote,
  updateSettingsRuntimeChat,
  updateSettingsRuntimeInstructions,
  updateSettingsRuntimeNodeExecutor,
  updateSettingsRuntimeNodeSkillBinding,
  updateSettingsRuntimeRag,
  updateMcp,
  updateModel,
  updateDefaultModel,
  updateScript,
  updateSkill,
  updateMemory,
  updateMilestone,
  updateFlowchart,
  updateFlowchartGraph,
  updateChatThreadConfig,
  updatePlan,
  updatePlanStage,
  updatePlanTask,
  updateTaskTemplate,
  updateAgent,
  updateAgentPriority,
  deleteMcp,
  deleteModel,
  deleteScript,
  deleteSkill,
  validateFlowchart,
} from './studioApi'

describe('studioApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('health and chat activity endpoints map to expected api paths', () => {
    getBackendHealth()
    getChatActivity()
    getChatActivity({ limit: 12.7 })
    getChatActivity({
      limit: 50,
      eventClass: 'thread',
      eventType: 'created',
      reasonCode: 'RAG_RETRIEVAL_FAILED',
      threadId: '7',
    })

    expect(requestJson).toHaveBeenNthCalledWith(1, '/health')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/chat/activity?limit=10')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/chat/activity?limit=12')
    expect(requestJson).toHaveBeenNthCalledWith(
      4,
      '/chat/activity?limit=50&event_class=thread&event_type=created&reason_code=RAG_RETRIEVAL_FAILED&thread_id=7',
    )
  })

  test('chat runtime mutation endpoints map to expected api paths', () => {
    getChatRuntime()
    getChatRuntime({ threadId: '3' })
    createChatThread({
      title: 'New chat',
      modelId: 4,
      responseComplexity: 'high',
      mcpServerIds: [1, '2'],
      ragCollections: ['docs', ' code '],
    })
    updateChatThreadConfig(5, {
      modelId: null,
      responseComplexity: 'medium',
      mcpServerIds: ['7', 'bad', 8],
      ragCollections: ['docs', ''],
    })
    archiveChatThread(5)
    clearChatThread(5)
    sendChatTurn(5, ' hello ')

    expect(requestJson).toHaveBeenNthCalledWith(1, '/chat/runtime')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/chat/runtime?thread_id=3')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/chat/threads', {
      method: 'POST',
      body: {
        title: 'New chat',
        model_id: 4,
        response_complexity: 'high',
        mcp_server_ids: [1, 2],
        rag_collections: ['docs', 'code'],
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(4, '/chat/threads/5/config', {
      method: 'POST',
      body: {
        model_id: null,
        response_complexity: 'medium',
        mcp_server_ids: [7, 8],
        rag_collections: ['docs'],
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(5, '/chat/threads/5/archive', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(6, '/chat/threads/5/clear', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/chat/threads/5/turn', {
      method: 'POST',
      body: { message: 'hello' },
    })
  })

  test('run and node reads validate ids and call expected endpoints', () => {
    getRun('7')
    getNodeStatus(11)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/runs/7')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/nodes/11/status')
  })

  test('chat thread read validates ids and preserves critical failure messaging', () => {
    expect(() => getChatThread('')).toThrow('threadId must be a positive integer.')
    expect(() => getChatRuntime({ threadId: 'bad' })).toThrow('threadId must be a positive integer.')
    expect(() => createChatThread({ modelId: 0 })).toThrow('modelId must be a positive integer when provided.')
    expect(() => sendChatTurn(1, '   ')).toThrow('message is required.')
    expect(() => getRun(0)).toThrow('runId must be a positive integer.')
    expect(() => getNodeStatus('bad')).toThrow('nodeId must be a positive integer.')
  })

  test('agent endpoints map to expected api paths', () => {
    getAgents()
    getAgentMeta()
    getAgent(4)
    createAgent({ name: 'A', description: 'D', roleId: 2 })
    updateAgent(4, { name: 'B', description: 'E', roleId: null })
    deleteAgent(4)
    startAgent(4)
    stopAgent(4)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/agents')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/agents/new')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/agents/4')
    expect(requestJson).toHaveBeenNthCalledWith(4, '/agents', {
      method: 'POST',
      body: { name: 'A', description: 'D', role_id: 2 },
    })
    expect(requestJson).toHaveBeenNthCalledWith(5, '/agents/4', {
      method: 'POST',
      body: { name: 'B', description: 'E', role_id: null },
    })
    expect(requestJson).toHaveBeenNthCalledWith(6, '/agents/4/delete', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/agents/4/start', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(8, '/agents/4/stop', { method: 'POST' })
  })

  test('agent priority and skill mutation endpoints map to expected api paths', () => {
    createAgentPriority(3, 'Do high-value work first')
    updateAgentPriority(3, 7, 'Updated')
    moveAgentPriority(3, 7, 'up')
    deleteAgentPriority(3, 7)
    attachAgentSkill(3, 9)
    moveAgentSkill(3, 9, 'down')
    detachAgentSkill(3, 9)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/agents/3/priorities', {
      method: 'POST',
      body: { content: 'Do high-value work first' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(2, '/agents/3/priorities/7', {
      method: 'POST',
      body: { content: 'Updated' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(3, '/agents/3/priorities/7/move', {
      method: 'POST',
      body: { direction: 'up' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(4, '/agents/3/priorities/7/delete', {
      method: 'POST',
    })
    expect(requestJson).toHaveBeenNthCalledWith(5, '/agents/3/skills', {
      method: 'POST',
      body: { skill_id: 9 },
    })
    expect(requestJson).toHaveBeenNthCalledWith(6, '/agents/3/skills/9/move', {
      method: 'POST',
      body: { direction: 'down' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/agents/3/skills/9/delete', {
      method: 'POST',
    })
  })

  test('agent endpoint id validation errors are explicit', () => {
    expect(() => getAgent('bad')).toThrow('agentId must be a positive integer.')
    expect(() => deleteAgent(0)).toThrow('agentId must be a positive integer.')
    expect(() => attachAgentSkill(2, 'x')).toThrow('skillId must be a positive integer.')
    expect(() => updateAgentPriority(2, 'bad', 'x')).toThrow('priorityId must be a positive integer.')
  })

  test('stage 3 runs endpoints map to expected api paths', () => {
    getRuns()
    getRuns({ page: 2.8, perPage: 25.1 })
    getRunMeta({ agentId: 4 })
    getRunEdit(11)
    deleteRun(11)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/runs?page=1&per_page=10')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/runs?page=2&per_page=25')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/runs/new?agent_id=4')
    expect(requestJson).toHaveBeenNthCalledWith(4, '/runs/11/edit')
    expect(requestJson).toHaveBeenNthCalledWith(5, '/runs/11/delete', { method: 'POST' })
  })

  test('stage 3 nodes endpoints map to expected api paths', () => {
    getNodes()
    getNodes({ page: 3, perPage: 50, agentId: 7, nodeType: 'task', status: 'running' })
    getNode(8)
    getNodeMeta()
    createNode({
      agentId: 3,
      prompt: 'run this',
      integrationKeys: ['github'],
      scriptIdsByType: { pre_init: [1] },
      scriptIds: [2],
    })
    cancelNode(8)
    deleteNode(8)
    removeNodeAttachment(8, 12)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/nodes?page=1&per_page=10')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/nodes?page=3&per_page=50&agent_id=7&node_type=task&status=running')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/nodes/8')
    expect(requestJson).toHaveBeenNthCalledWith(4, '/nodes/new')
    expect(requestJson).toHaveBeenNthCalledWith(5, '/nodes/new', {
      method: 'POST',
      body: {
        agent_id: 3,
        prompt: 'run this',
        integration_keys: ['github'],
        script_ids_by_type: { pre_init: [1] },
        script_ids: [2],
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(6, '/nodes/8/cancel', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/nodes/8/delete', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(8, '/nodes/8/attachments/12/remove', { method: 'POST' })
  })

  test('stage 3 node create uses multipart payload when attachments are present', () => {
    const attachment = new File(['node attachment'], 'node.txt', { type: 'text/plain' })
    createNode({
      agentId: 3,
      prompt: 'run this',
      integrationKeys: ['github', 'jira'],
      scriptIdsByType: { pre_init: [1, 2] },
      scriptIds: [9],
      attachments: [attachment],
    })

    expect(requestJson).toHaveBeenCalledTimes(1)
    expect(requestJson).toHaveBeenNthCalledWith(1, '/nodes/new', {
      method: 'POST',
      body: expect.any(FormData),
    })

    const call = requestJson.mock.calls[0]
    const options = call[1]
    const formData = options.body
    expect(formData.get('agent_id')).toBe('3')
    expect(formData.get('prompt')).toBe('run this')
    expect(formData.getAll('integration_keys')).toEqual(['github', 'jira'])
    expect(formData.getAll('pre_init_script_ids')).toEqual(['1', '2'])
    expect(formData.getAll('script_ids')).toEqual(['9'])
    expect(formData.getAll('attachments')).toEqual([attachment])
  })

  test('stage 3 quick endpoint maps to expected api paths', () => {
    getQuickTaskMeta()
    createQuickTask({
      prompt: 'hello',
      agentId: 2,
      modelId: 3,
      mcpServerIds: [4],
      integrationKeys: ['github'],
    })

    expect(requestJson).toHaveBeenNthCalledWith(1, '/quick')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/quick', {
      method: 'POST',
      body: {
        prompt: 'hello',
        agent_id: 2,
        model_id: 3,
        mcp_server_ids: [4],
        integration_keys: ['github'],
      },
    })
  })

  test('stage 3 quick create uses multipart payload when attachments are present', () => {
    const attachment = new File(['quick attachment'], 'quick.txt', { type: 'text/plain' })
    createQuickTask({
      prompt: 'hello',
      agentId: 2,
      modelId: 3,
      mcpServerIds: [4],
      integrationKeys: ['github'],
      attachments: [attachment],
    })

    expect(requestJson).toHaveBeenCalledTimes(1)
    expect(requestJson).toHaveBeenNthCalledWith(1, '/quick', {
      method: 'POST',
      body: expect.any(FormData),
    })

    const call = requestJson.mock.calls[0]
    const options = call[1]
    const formData = options.body
    expect(formData.get('prompt')).toBe('hello')
    expect(formData.get('agent_id')).toBe('2')
    expect(formData.get('model_id')).toBe('3')
    expect(formData.getAll('mcp_server_ids')).toEqual(['4'])
    expect(formData.getAll('integration_keys')).toEqual(['github'])
    expect(formData.getAll('attachments')).toEqual([attachment])
  })

  test('stage 4 plans endpoints map to expected api paths', () => {
    getPlans()
    getPlan(5)
    getPlanMeta()
    getPlanEdit(5)
    updatePlan(5, { name: 'Plan', description: 'Desc', completedAt: '2026-02-17T10:00' })
    deletePlan(5)
    createPlanStage(5, { name: 'Stage', description: 'Desc', completedAt: '' })
    updatePlanStage(5, 7, { name: 'Stage 2', description: 'D', completedAt: '' })
    deletePlanStage(5, 7)
    createPlanTask(5, 7, { name: 'Task', description: 'Desc', completedAt: '' })
    updatePlanTask(5, 7, 9, { name: 'Task 2', description: 'D', completedAt: '' })
    deletePlanTask(5, 7, 9)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/plans?page=1&per_page=20')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/plans/5')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/plans/new')
    expect(requestJson).toHaveBeenNthCalledWith(4, '/plans/5/edit')
    expect(requestJson).toHaveBeenNthCalledWith(5, '/plans/5', {
      method: 'POST',
      body: { name: 'Plan', description: 'Desc', completed_at: '2026-02-17T10:00' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(6, '/plans/5/delete', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/plans/5/stages', {
      method: 'POST',
      body: { name: 'Stage', description: 'Desc', completed_at: '' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(8, '/plans/5/stages/7', {
      method: 'POST',
      body: { name: 'Stage 2', description: 'D', completed_at: '' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(9, '/plans/5/stages/7/delete', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(10, '/plans/5/stages/7/tasks', {
      method: 'POST',
      body: { name: 'Task', description: 'Desc', completed_at: '' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(11, '/plans/5/stages/7/tasks/9', {
      method: 'POST',
      body: { name: 'Task 2', description: 'D', completed_at: '' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(12, '/plans/5/stages/7/tasks/9/delete', { method: 'POST' })
  })

  test('stage 4 milestones and memories endpoints map to expected api paths', () => {
    getMilestones()
    getMilestoneMeta()
    getMilestone(3)
    getMilestoneEdit(3)
    updateMilestone(3, { name: 'M', progressPercent: 10 })
    deleteMilestone(3)
    getMemories()
    getMemoryMeta()
    getMemory(4)
    getMemoryEdit(4)
    updateMemory(4, { description: 'Updated memory' })
    deleteMemory(4)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/milestones?page=1&per_page=20')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/milestones/new')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/milestones/3')
    expect(requestJson).toHaveBeenNthCalledWith(4, '/milestones/3/edit')
    expect(requestJson).toHaveBeenNthCalledWith(5, '/milestones/3', {
      method: 'POST',
      body: {
        name: 'M',
        description: '',
        status: '',
        priority: '',
        owner: '',
        start_date: '',
        due_date: '',
        progress_percent: 10,
        health: '',
        success_criteria: '',
        dependencies: '',
        links: '',
        latest_update: '',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(6, '/milestones/3/delete', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/memories?page=1&per_page=20')
    expect(requestJson).toHaveBeenNthCalledWith(8, '/memories/new')
    expect(requestJson).toHaveBeenNthCalledWith(9, '/memories/4')
    expect(requestJson).toHaveBeenNthCalledWith(10, '/memories/4/edit')
    expect(requestJson).toHaveBeenNthCalledWith(11, '/memories/4', {
      method: 'POST',
      body: { description: 'Updated memory' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(12, '/memories/4/delete', { method: 'POST' })
  })

  test('stage 4 task template endpoints map to expected api paths', () => {
    getTaskTemplates()
    getTaskTemplateMeta()
    getTaskTemplate(6)
    getTaskTemplateEdit(6)
    updateTaskTemplate(6, { name: 'Template', description: 'Desc', prompt: 'Prompt', agentId: 3 })
    removeTaskTemplateAttachment(6, 8)
    deleteTaskTemplate(6)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/task-templates?page=1&per_page=20')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/task-templates/new')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/task-templates/6')
    expect(requestJson).toHaveBeenNthCalledWith(4, '/task-templates/6/edit')
    expect(requestJson).toHaveBeenNthCalledWith(5, '/task-templates/6', {
      method: 'POST',
      body: { name: 'Template', description: 'Desc', prompt: 'Prompt', agent_id: 3 },
    })
    expect(requestJson).toHaveBeenNthCalledWith(6, '/task-templates/6/attachments/8/remove', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/task-templates/6/delete', { method: 'POST' })
  })

  test('stage 5 flowchart endpoints map to expected api paths', () => {
    getFlowcharts()
    getFlowchartMeta()
    createFlowchart({
      name: 'Release Readiness',
      description: 'weekly release orchestration',
      maxNodeExecutions: 20,
      maxRuntimeMinutes: 45,
      maxParallelNodes: 2,
    })
    getFlowchart(4)
    getFlowchartEdit(4)
    updateFlowchart(4, {
      name: 'Release Readiness v2',
      description: 'updated',
      maxNodeExecutions: 30,
      maxRuntimeMinutes: 60,
      maxParallelNodes: 3,
    })
    deleteFlowchart(4)
    getFlowchartGraph(4)
    updateFlowchartGraph(4, { nodes: [{ id: 1, node_type: 'start' }], edges: [] })
    validateFlowchart(4)
    runFlowchart(4)
    getFlowchartHistory(4)
    getFlowchartHistoryRun(4, 9)
    getFlowchartRun(9)
    getFlowchartRunStatus(9)
    getFlowchartRuntime(4)
    cancelFlowchartRun(9, { force: true })
    getFlowchartNodeUtilities(4, 11)
    setFlowchartNodeModel(4, 11, { modelId: 3 })
    attachFlowchartNodeMcp(4, 11, { mcpServerId: 7 })
    detachFlowchartNodeMcp(4, 11, 7)
    attachFlowchartNodeScript(4, 11, { scriptId: 8 })
    detachFlowchartNodeScript(4, 11, 8)
    reorderFlowchartNodeScripts(4, 11, { scriptIds: [8, 5] })
    attachFlowchartNodeSkill(4, 11, { skillId: 2 })
    detachFlowchartNodeSkill(4, 11, 2)
    reorderFlowchartNodeSkills(4, 11, { skillIds: [2, 9] })

    expect(requestJson).toHaveBeenNthCalledWith(1, '/flowcharts')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/flowcharts/new')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/flowcharts', {
      method: 'POST',
      body: {
        name: 'Release Readiness',
        description: 'weekly release orchestration',
        max_node_executions: 20,
        max_runtime_minutes: 45,
        max_parallel_nodes: 2,
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(4, '/flowcharts/4')
    expect(requestJson).toHaveBeenNthCalledWith(5, '/flowcharts/4/edit')
    expect(requestJson).toHaveBeenNthCalledWith(6, '/flowcharts/4', {
      method: 'POST',
      body: {
        name: 'Release Readiness v2',
        description: 'updated',
        max_node_executions: 30,
        max_runtime_minutes: 60,
        max_parallel_nodes: 3,
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/flowcharts/4/delete', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(8, '/flowcharts/4/graph')
    expect(requestJson).toHaveBeenNthCalledWith(9, '/flowcharts/4/graph', {
      method: 'POST',
      body: { nodes: [{ id: 1, node_type: 'start' }], edges: [] },
    })
    expect(requestJson).toHaveBeenNthCalledWith(10, '/flowcharts/4/validate')
    expect(requestJson).toHaveBeenNthCalledWith(11, '/flowcharts/4/run', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(12, '/flowcharts/4/history')
    expect(requestJson).toHaveBeenNthCalledWith(13, '/flowcharts/4/history/9')
    expect(requestJson).toHaveBeenNthCalledWith(14, '/flowcharts/runs/9')
    expect(requestJson).toHaveBeenNthCalledWith(15, '/flowcharts/runs/9/status')
    expect(requestJson).toHaveBeenNthCalledWith(16, '/flowcharts/4/runtime')
    expect(requestJson).toHaveBeenNthCalledWith(17, '/flowcharts/runs/9/cancel', {
      method: 'POST',
      body: { force: true },
    })
    expect(requestJson).toHaveBeenNthCalledWith(18, '/flowcharts/4/nodes/11/utilities')
    expect(requestJson).toHaveBeenNthCalledWith(19, '/flowcharts/4/nodes/11/model', {
      method: 'POST',
      body: { model_id: 3 },
    })
    expect(requestJson).toHaveBeenNthCalledWith(20, '/flowcharts/4/nodes/11/mcp-servers', {
      method: 'POST',
      body: { mcp_server_id: 7 },
    })
    expect(requestJson).toHaveBeenNthCalledWith(21, '/flowcharts/4/nodes/11/mcp-servers/7/delete', {
      method: 'POST',
    })
    expect(requestJson).toHaveBeenNthCalledWith(22, '/flowcharts/4/nodes/11/scripts', {
      method: 'POST',
      body: { script_id: 8 },
    })
    expect(requestJson).toHaveBeenNthCalledWith(23, '/flowcharts/4/nodes/11/scripts/8/delete', {
      method: 'POST',
    })
    expect(requestJson).toHaveBeenNthCalledWith(24, '/flowcharts/4/nodes/11/scripts/reorder', {
      method: 'POST',
      body: { script_ids: [8, 5] },
    })
    expect(requestJson).toHaveBeenNthCalledWith(25, '/flowcharts/4/nodes/11/skills', {
      method: 'POST',
      body: { skill_id: 2 },
    })
    expect(requestJson).toHaveBeenNthCalledWith(26, '/flowcharts/4/nodes/11/skills/2/delete', {
      method: 'POST',
    })
    expect(requestJson).toHaveBeenNthCalledWith(27, '/flowcharts/4/nodes/11/skills/reorder', {
      method: 'POST',
      body: { skill_ids: [2, 9] },
    })
  })

  test('stage 6 settings endpoints map to expected api paths', () => {
    getSettingsCore()
    getSettingsProvider()
    getSettingsProvider({ section: 'codex' })
    getSettingsProvider({ section: 'vllm-local' })
    updateSettingsProviderControls({
      defaultProvider: 'codex',
      enabledProviders: ['codex', 'gemini'],
    })
    updateSettingsProviderCodex({ apiKey: 'c-key' })
    updateSettingsProviderGemini({ apiKey: 'g-key' })
    updateSettingsProviderClaude({ apiKey: 'a-key' })
    updateSettingsProviderVllmLocal({ model: 'custom/qwen', huggingfaceToken: 'hf-key' })
    updateSettingsProviderVllmRemote({
      baseUrl: 'http://vllm.local:8000/v1',
      apiKey: 'vllm-key',
      model: 'qwen3-30b-a3b',
      models: 'qwen3-30b-a3b,llama3.1',
    })
    getSettingsRuntime()
    getSettingsRuntime({ section: 'rag' })
    getSettingsRuntime({ section: 'chat' })
    updateSettingsRuntimeInstructions({
      instruction_native_enabled_codex: true,
      instruction_fallback_enabled_codex: false,
    })
    updateSettingsRuntimeNodeSkillBinding({ mode: 'warn' })
    updateSettingsRuntimeNodeExecutor({
      provider: 'kubernetes',
      workspaceIdentityKey: 'workspace',
      dispatchTimeoutSeconds: 60,
      executionTimeoutSeconds: 1800,
      logCollectionTimeoutSeconds: 30,
      cancelGraceTimeoutSeconds: 30,
      cancelForceKillEnabled: true,
      k8sKubeconfig: '',
      k8sKubeconfigClear: false,
      k8sNamespace: 'llmctl',
      k8sImage: 'llmctl/studio:dev',
      k8sServiceAccount: 'studio-runner',
      k8sGpuLimit: 0,
      k8sJobTtlSeconds: 600,
      k8sImagePullSecretsJson: '[]',
      k8sInCluster: true,
    })
    updateSettingsRuntimeRag({
      dbProvider: 'chroma',
      embedProvider: 'codex',
      chatProvider: 'codex',
      openaiEmbedModel: 'text-embedding-3-small',
      geminiEmbedModel: 'gemini-embedding-001',
      openaiChatModel: 'gpt-4o-mini',
      geminiChatModel: 'gemini-2.5-flash',
      chatTemperature: '0.2',
      chatResponseStyle: 'balanced',
      chatTopK: '5',
      chatMaxHistory: '8',
      chatMaxContextChars: '12000',
      chatSnippetChars: '600',
      chatContextBudgetTokens: '8000',
      indexParallelWorkers: '1',
      embedParallelRequests: '1',
    })
    updateSettingsRuntimeChat({
      historyBudgetPercent: 45,
      ragBudgetPercent: 35,
      mcpBudgetPercent: 20,
      compactionTriggerPercent: 90,
      compactionTargetPercent: 70,
      preserveRecentTurns: 3,
      ragTopK: 5,
      defaultContextWindowTokens: 64000,
      maxCompactionSummaryChars: 4000,
      returnTo: 'runtime',
    })
    getSettingsChat()
    updateSettingsChatDefaults({
      defaultModelId: 4,
      defaultResponseComplexity: 'high',
      defaultMcpServerIds: [2, 3],
      defaultRagCollections: ['repo-docs', 'kb-prod'],
    })

    expect(requestJson).toHaveBeenNthCalledWith(1, '/settings/core')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/settings/provider')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/settings/provider/codex')
    expect(requestJson).toHaveBeenNthCalledWith(4, '/settings/provider/vllm-local')
    expect(requestJson).toHaveBeenNthCalledWith(5, '/settings/provider', {
      method: 'POST',
      body: {
        default_provider: 'codex',
        provider_enabled_codex: true,
        provider_enabled_gemini: true,
        provider_enabled_claude: false,
        provider_enabled_vllm_local: false,
        provider_enabled_vllm_remote: false,
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(6, '/settings/provider/codex', {
      method: 'POST',
      body: { codex_api_key: 'c-key' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/settings/provider/gemini', {
      method: 'POST',
      body: { gemini_api_key: 'g-key' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(8, '/settings/provider/claude', {
      method: 'POST',
      body: { claude_api_key: 'a-key' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(9, '/settings/provider/vllm-local', {
      method: 'POST',
      body: { vllm_local_model: 'custom/qwen', vllm_local_hf_token: 'hf-key' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(10, '/settings/provider/vllm-remote', {
      method: 'POST',
      body: {
        vllm_remote_base_url: 'http://vllm.local:8000/v1',
        vllm_remote_api_key: 'vllm-key',
        vllm_remote_model: 'qwen3-30b-a3b',
        vllm_remote_models: 'qwen3-30b-a3b,llama3.1',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(11, '/settings/runtime')
    expect(requestJson).toHaveBeenNthCalledWith(12, '/settings/runtime/rag')
    expect(requestJson).toHaveBeenNthCalledWith(13, '/settings/runtime/chat')
    expect(requestJson).toHaveBeenNthCalledWith(14, '/settings/runtime/instructions', {
      method: 'POST',
      body: {
        instruction_native_enabled_codex: true,
        instruction_fallback_enabled_codex: false,
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(15, '/settings/runtime/node-skill-binding', {
      method: 'POST',
      body: { node_skill_binding_mode: 'warn' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(16, '/settings/runtime/node-executor', {
      method: 'POST',
      body: {
        provider: 'kubernetes',
        workspace_identity_key: 'workspace',
        dispatch_timeout_seconds: 60,
        execution_timeout_seconds: 1800,
        log_collection_timeout_seconds: 30,
        cancel_grace_timeout_seconds: 30,
        cancel_force_kill_enabled: true,
        k8s_kubeconfig: '',
        k8s_kubeconfig_clear: false,
        k8s_namespace: 'llmctl',
        k8s_image: 'llmctl/studio:dev',
        k8s_service_account: 'studio-runner',
        k8s_gpu_limit: 0,
        k8s_job_ttl_seconds: 600,
        k8s_image_pull_secrets_json: '[]',
        k8s_in_cluster: true,
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(17, '/settings/runtime/rag', {
      method: 'POST',
      body: {
        rag_db_provider: 'chroma',
        rag_embed_provider: 'codex',
        rag_chat_provider: 'codex',
        rag_openai_embed_model: 'text-embedding-3-small',
        rag_gemini_embed_model: 'gemini-embedding-001',
        rag_openai_chat_model: 'gpt-4o-mini',
        rag_gemini_chat_model: 'gemini-2.5-flash',
        rag_chat_temperature: '0.2',
        rag_chat_response_style: 'balanced',
        rag_chat_top_k: '5',
        rag_chat_max_history: '8',
        rag_chat_max_context_chars: '12000',
        rag_chat_snippet_chars: '600',
        rag_chat_context_budget_tokens: '8000',
        rag_index_parallel_workers: '1',
        rag_embed_parallel_requests: '1',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(18, '/settings/runtime/chat', {
      method: 'POST',
      body: {
        history_budget_percent: 45,
        rag_budget_percent: 35,
        mcp_budget_percent: 20,
        compaction_trigger_percent: 90,
        compaction_target_percent: 70,
        preserve_recent_turns: 3,
        rag_top_k: 5,
        default_context_window_tokens: 64000,
        max_compaction_summary_chars: 4000,
        return_to: 'runtime',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(19, '/settings/chat')
    expect(requestJson).toHaveBeenNthCalledWith(20, '/settings/chat/defaults', {
      method: 'POST',
      body: {
        default_model_id: 4,
        default_response_complexity: 'high',
        default_mcp_server_ids: [2, 3],
        default_rag_collections: ['repo-docs', 'kb-prod'],
      },
    })
  })

  test('stage 6 integrations endpoints map to expected api paths', () => {
    getSettingsIntegrations()
    getSettingsIntegrations({ section: 'google-cloud' })
    getSettingsIntegrations({ section: 'google-workspace' })
    updateSettingsIntegrationsGit({ gitconfigContent: '[user]\\nname = studio\\n' })
    updateSettingsIntegrationsGithub({
      pat: 'ghp_xxx',
      repo: 'org/repo',
      clearSshKey: true,
      action: 'refresh',
    })
    updateSettingsIntegrationsJira({
      apiKey: 'jira-key',
      email: 'owner@example.com',
      site: 'https://example.atlassian.net',
      projectKey: 'OPS',
      board: '42',
      action: 'refresh',
    })
    updateSettingsIntegrationsConfluence({
      apiKey: 'conf-key',
      email: 'owner@example.com',
      site: 'https://example.atlassian.net/wiki',
      space: 'ENG',
      action: 'refresh',
    })
    updateSettingsIntegrationsGoogleCloud({
      serviceAccountJson: '{"type":"service_account"}',
      projectId: 'llmctl-prod',
      mcpEnabled: true,
    })
    updateSettingsIntegrationsGoogleWorkspace({
      serviceAccountJson: '{"type":"service_account"}',
      delegatedUserEmail: 'workspace-admin@example.com',
      mcpEnabled: false,
    })
    updateSettingsIntegrationsHuggingface({ token: 'hf_xxx' })
    updateSettingsIntegrationsChroma({ host: 'llmctl-chromadb', port: 8000, ssl: true })

    expect(requestJson).toHaveBeenNthCalledWith(1, '/settings/integrations/git')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/settings/integrations/google-cloud')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/settings/integrations/google-workspace')
    expect(requestJson).toHaveBeenNthCalledWith(4, '/settings/integrations/git', {
      method: 'POST',
      body: {
        gitconfig_content: '[user]\\nname = studio\\n',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(5, '/settings/integrations/github', {
      method: 'POST',
      body: {
        github_pat: 'ghp_xxx',
        github_repo: 'org/repo',
        github_ssh_key_clear: true,
        action: 'refresh',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(6, '/settings/integrations/jira', {
      method: 'POST',
      body: {
        jira_api_key: 'jira-key',
        jira_email: 'owner@example.com',
        jira_site: 'https://example.atlassian.net',
        jira_project_key: 'OPS',
        jira_board: '42',
        action: 'refresh',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/settings/integrations/confluence', {
      method: 'POST',
      body: {
        confluence_api_key: 'conf-key',
        confluence_email: 'owner@example.com',
        confluence_site: 'https://example.atlassian.net/wiki',
        confluence_space: 'ENG',
        action: 'refresh',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(8, '/settings/integrations/google-cloud', {
      method: 'POST',
      body: {
        google_cloud_service_account_json: '{"type":"service_account"}',
        google_cloud_project_id: 'llmctl-prod',
        google_cloud_mcp_enabled: true,
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(9, '/settings/integrations/google-workspace', {
      method: 'POST',
      body: {
        workspace_service_account_json: '{"type":"service_account"}',
        workspace_delegated_user_email: 'workspace-admin@example.com',
        google_workspace_mcp_enabled: false,
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(10, '/settings/integrations/huggingface', {
      method: 'POST',
      body: {
        vllm_local_hf_token: 'hf_xxx',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(11, '/settings/integrations/chroma', {
      method: 'POST',
      body: {
        chroma_host: 'llmctl-chromadb',
        chroma_port: 8000,
        chroma_ssl: true,
      },
    })
  })

  test('stage 7 skills endpoints map to expected api paths', () => {
    getSkills()
    getSkillMeta()
    createSkill({
      name: 'test-skill',
      displayName: 'Test Skill',
      description: 'desc',
      version: '1.0.0',
      status: 'active',
      skillMd: '# Skill',
      sourceRef: 'web:create',
      extraFiles: [{ path: 'notes.md', content: 'hello' }],
    })
    getSkillImportMeta()
    previewSkillImport({ sourceKind: 'upload', bundlePayload: '{"metadata":{}}' })
    importSkillBundle({ sourceKind: 'upload', bundlePayload: '{"metadata":{}}' })
    getSkill(4, { version: '2.0.0' })
    getSkillEdit(4)
    updateSkill(4, {
      displayName: 'Updated Skill',
      description: 'updated',
      status: 'active',
      newVersion: '2.0.0',
      newSkillMd: '# Updated',
      existingFiles: [{ original_path: 'notes.md', path: 'notes.md', delete: false }],
      extraFiles: [{ path: 'extra.md', content: 'new' }],
      sourceRef: 'web:update',
    })
    deleteSkill(4)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/skills')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/skills/new')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/skills', {
      method: 'POST',
      body: {
        name: 'test-skill',
        display_name: 'Test Skill',
        description: 'desc',
        version: '1.0.0',
        status: 'active',
        skill_md: '# Skill',
        source_ref: 'web:create',
        extra_files: [{ path: 'notes.md', content: 'hello' }],
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(4, '/skills/import')
    expect(requestJson).toHaveBeenNthCalledWith(5, '/skills/import', {
      method: 'POST',
      body: {
        action: 'preview',
        source_kind: 'upload',
        local_path: '',
        source_ref: '',
        actor: '',
        git_url: '',
        bundle_payload: '{"metadata":{}}',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(6, '/skills/import', {
      method: 'POST',
      body: {
        action: 'import',
        source_kind: 'upload',
        local_path: '',
        source_ref: '',
        actor: '',
        git_url: '',
        bundle_payload: '{"metadata":{}}',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/skills/4?version=2.0.0')
    expect(requestJson).toHaveBeenNthCalledWith(8, '/skills/4/edit')
    expect(requestJson).toHaveBeenNthCalledWith(9, '/skills/4', {
      method: 'POST',
      body: {
        display_name: 'Updated Skill',
        description: 'updated',
        status: 'active',
        new_version: '2.0.0',
        new_skill_md: '# Updated',
        existing_files: [{ original_path: 'notes.md', path: 'notes.md', delete: false }],
        extra_files: [{ path: 'extra.md', content: 'new' }],
        source_ref: 'web:update',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(10, '/skills/4/delete', { method: 'POST' })
  })

  test('stage 7 script, attachment, model, and mcp endpoints map to expected api paths', () => {
    getScripts()
    getScriptMeta()
    createScript({
      fileName: 'example.py',
      description: 'desc',
      scriptType: 'pre_init',
      content: 'print(1)',
    })
    getScript(5)
    getScriptEdit(5)
    updateScript(5, {
      fileName: 'example.py',
      description: 'updated',
      scriptType: 'post_response',
      content: 'print(2)',
    })
    deleteScript(5)

    getAttachments()
    getAttachment(6)
    deleteAttachment(6)

    getModels()
    getModelMeta()
    createModel({
      name: 'Codex',
      description: 'desc',
      provider: 'codex',
      config: { model: 'gpt-5-codex' },
    })
    getModel(7)
    getModelEdit(7)
    updateModel(7, {
      name: 'Codex Updated',
      description: 'updated',
      provider: 'codex',
      config: { model: 'gpt-5-codex' },
    })
    updateDefaultModel(7, true)
    deleteModel(7)

    getMcps()
    getMcpMeta()
    createMcp({
      name: 'Custom MCP',
      serverKey: 'custom_server',
      description: 'desc',
      config: { command: 'python3', args: ['-V'] },
    })
    getMcp(8)
    getMcpEdit(8)
    updateMcp(8, {
      name: 'Custom MCP 2',
      serverKey: 'custom_server',
      description: 'updated',
      config: { command: 'python3', args: ['-V'] },
    })
    deleteMcp(8)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/scripts')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/scripts/new')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/scripts', {
      method: 'POST',
      body: {
        file_name: 'example.py',
        description: 'desc',
        script_type: 'pre_init',
        content: 'print(1)',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(4, '/scripts/5')
    expect(requestJson).toHaveBeenNthCalledWith(5, '/scripts/5/edit')
    expect(requestJson).toHaveBeenNthCalledWith(6, '/scripts/5', {
      method: 'POST',
      body: {
        file_name: 'example.py',
        description: 'updated',
        script_type: 'post_response',
        content: 'print(2)',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/scripts/5/delete', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(8, '/attachments')
    expect(requestJson).toHaveBeenNthCalledWith(9, '/attachments/6')
    expect(requestJson).toHaveBeenNthCalledWith(10, '/attachments/6/delete', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(11, '/models')
    expect(requestJson).toHaveBeenNthCalledWith(12, '/models/new')
    expect(requestJson).toHaveBeenNthCalledWith(13, '/models', {
      method: 'POST',
      body: {
        name: 'Codex',
        description: 'desc',
        provider: 'codex',
        config: { model: 'gpt-5-codex' },
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(14, '/models/7')
    expect(requestJson).toHaveBeenNthCalledWith(15, '/models/7/edit')
    expect(requestJson).toHaveBeenNthCalledWith(16, '/models/7', {
      method: 'POST',
      body: {
        name: 'Codex Updated',
        description: 'updated',
        provider: 'codex',
        config: { model: 'gpt-5-codex' },
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(17, '/models/default', {
      method: 'POST',
      body: {
        model_id: 7,
        is_default: true,
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(18, '/models/7/delete', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(19, '/mcps')
    expect(requestJson).toHaveBeenNthCalledWith(20, '/mcps/new')
    expect(requestJson).toHaveBeenNthCalledWith(21, '/mcps', {
      method: 'POST',
      body: {
        name: 'Custom MCP',
        server_key: 'custom_server',
        description: 'desc',
        config: { command: 'python3', args: ['-V'] },
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(22, '/mcps/8')
    expect(requestJson).toHaveBeenNthCalledWith(23, '/mcps/8/edit')
    expect(requestJson).toHaveBeenNthCalledWith(24, '/mcps/8', {
      method: 'POST',
      body: {
        name: 'Custom MCP 2',
        server_key: 'custom_server',
        description: 'updated',
        config: { command: 'python3', args: ['-V'] },
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(25, '/mcps/8/delete', { method: 'POST' })
  })

  test('stage 8 external tool and rag endpoints map to expected api paths', () => {
    getGithubWorkspace({ tab: 'pulls', prStatus: 'open', prAuthor: 'alice', path: 'src' })
    getGithubPullRequest(9)
    getGithubPullRequest(9, { tab: 'commits' })
    runGithubPullRequestCodeReview(9, { prTitle: 'Improve API', prUrl: 'https://github.com/org/repo/pull/9' })
    getJiraWorkspace()
    getJiraIssue('OPS-42')
    getConfluenceWorkspace({ page: '12345' })
    getChromaCollections({ page: 2, perPage: 50 })
    getChromaCollection('docs')
    deleteChromaCollection('docs', { next: 'detail' })
    getRagSources()
    getRagSourceMeta()
    createRagSource({
      name: 'docs',
      kind: 'github',
      gitRepo: 'org/repo',
      gitBranch: 'main',
      indexScheduleValue: 12,
      indexScheduleUnit: 'hours',
      indexScheduleMode: 'delta',
    })
    getRagSource(10)
    getRagSourceEdit(10)
    updateRagSource(10, {
      name: 'docs-updated',
      kind: 'local',
      localPath: '/workspace/docs',
      indexScheduleValue: 1,
      indexScheduleUnit: 'days',
      indexScheduleMode: 'fresh',
    })
    quickIndexRagSource(10)
    quickDeltaIndexRagSource(10)
    getRagSourceStatus({ ids: [10, '11', 'x'] })
    deleteRagSource(10)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/github?tab=pulls&pr_status=open&pr_author=alice&path=src')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/github/pulls/9')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/github/pulls/9/commits')
    expect(requestJson).toHaveBeenNthCalledWith(4, '/github/pulls/9/code-review', {
      method: 'POST',
      body: {
        pr_title: 'Improve API',
        pr_url: 'https://github.com/org/repo/pull/9',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(5, '/jira')
    expect(requestJson).toHaveBeenNthCalledWith(6, '/jira/issues/OPS-42')
    expect(requestJson).toHaveBeenNthCalledWith(7, '/confluence?page=12345')
    expect(requestJson).toHaveBeenNthCalledWith(8, '/chroma/collections?page=2&per_page=50')
    expect(requestJson).toHaveBeenNthCalledWith(9, '/chroma/collections/detail?name=docs')
    expect(requestJson).toHaveBeenNthCalledWith(10, '/chroma/collections/delete', {
      method: 'POST',
      body: {
        collection_name: 'docs',
        next: 'detail',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(11, '/rag/sources')
    expect(requestJson).toHaveBeenNthCalledWith(12, '/rag/sources/new')
    expect(requestJson).toHaveBeenNthCalledWith(13, '/rag/sources', {
      method: 'POST',
      body: {
        name: 'docs',
        kind: 'github',
        local_path: '',
        git_repo: 'org/repo',
        git_branch: 'main',
        drive_folder_id: '',
        index_schedule_value: 12,
        index_schedule_unit: 'hours',
        index_schedule_mode: 'delta',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(14, '/rag/sources/10')
    expect(requestJson).toHaveBeenNthCalledWith(15, '/rag/sources/10/edit')
    expect(requestJson).toHaveBeenNthCalledWith(16, '/rag/sources/10', {
      method: 'POST',
      body: {
        name: 'docs-updated',
        kind: 'local',
        local_path: '/workspace/docs',
        git_repo: '',
        git_branch: '',
        drive_folder_id: '',
        index_schedule_value: 1,
        index_schedule_unit: 'days',
        index_schedule_mode: 'fresh',
      },
    })
    expect(requestJson).toHaveBeenNthCalledWith(17, '/rag/sources/10/quick-index', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(18, '/rag/sources/10/quick-delta-index', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(19, '/rag/sources/status?ids=10%2C11')
    expect(requestJson).toHaveBeenNthCalledWith(20, '/rag/sources/10/delete', { method: 'POST' })
  })
})
