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
  cancelFlowchartRun,
  cancelNode,
  createAgent,
  createAgentPriority,
  createFlowchart,
  createNode,
  createPlanStage,
  createPlanTask,
  createQuickTask,
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
  getChatThread,
  getMemory,
  getMemoryEdit,
  getMemoryMeta,
  getMemories,
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
  getTaskTemplate,
  getTaskTemplateEdit,
  getTaskTemplateMeta,
  getTaskTemplates,
  moveAgentPriority,
  moveAgentSkill,
  reorderFlowchartNodeScripts,
  reorderFlowchartNodeSkills,
  removeTaskTemplateAttachment,
  runFlowchart,
  setFlowchartNodeModel,
  startAgent,
  stopAgent,
  updateMemory,
  updateMilestone,
  updateFlowchart,
  updateFlowchartGraph,
  updatePlan,
  updatePlanStage,
  updatePlanTask,
  updateTaskTemplate,
  updateAgent,
  updateAgentPriority,
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

    expect(requestJson).toHaveBeenNthCalledWith(1, '/health')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/chat/activity?limit=10')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/chat/activity?limit=12')
  })

  test('run and node reads validate ids and call expected endpoints', () => {
    getRun('7')
    getNodeStatus(11)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/runs/7')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/nodes/11/status')
  })

  test('chat thread read validates ids and preserves critical failure messaging', () => {
    expect(() => getChatThread('')).toThrow('threadId must be a positive integer.')
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
})
