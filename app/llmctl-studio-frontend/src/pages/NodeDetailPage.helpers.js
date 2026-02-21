const OUTPUT_SUMMARY_PREFERRED_KEYS = [
  'message',
  'answer',
  'result',
  'summary',
  'content',
  'action_results',
]

const OUTPUT_DETAIL_METADATA_KEYS = [
  'node_type',
  'action',
  'status',
  'memory_id',
  'execution_status',
  'fallback_used',
  'action_prompt_template',
  'additive_prompt',
  'effective_prompt',
]

const LEGACY_DETAIL_BASE_FIELDS = [
  ['kind', 'Kind'],
  ['flowchart_id', 'Flowchart'],
  ['flowchart_run_id', 'Flowchart run'],
  ['flowchart_node_id', 'Flowchart node'],
  ['model_id', 'Model'],
  ['run_task_id', 'Autorun node'],
  ['celery_task_id', 'Celery task'],
  ['current_stage', 'Current stage'],
  ['status', 'Status'],
  ['created_at', 'Created'],
  ['started_at', 'Started'],
  ['finished_at', 'Finished'],
]

export const NODE_LEFT_DEFAULT_SECTION_KEY = 'results'

export const NODE_LEFT_SECTION_DEFINITIONS = [
  {
    key: 'input',
    label: 'Input',
    emptyMessage: 'No incoming connector context captured for this node run.',
  },
  {
    key: 'results',
    label: 'Results',
    emptyMessage: 'No results yet.',
  },
  {
    key: 'prompt',
    label: 'Prompt',
    emptyMessage: 'No prompt recorded.',
  },
  {
    key: 'agent',
    label: 'Agent',
    emptyMessage: 'No agent recorded for this node.',
  },
  {
    key: 'mcp_servers',
    label: 'MCP Servers',
    emptyMessage: 'No MCP servers selected.',
  },
  {
    key: 'collections',
    label: 'Collections',
    emptyMessage: 'No collections selected.',
  },
  {
    key: 'raw_json',
    label: 'Raw JSON',
    emptyMessage: 'No output yet.',
  },
  {
    key: 'details',
    label: 'Details',
    emptyMessage: 'No details yet.',
  },
]

function isPrimitiveOutputValue(value) {
  return (
    typeof value === 'string'
    || typeof value === 'number'
    || typeof value === 'boolean'
    || value == null
  )
}

function isSummaryOutputValue(value) {
  if (isPrimitiveOutputValue(value)) {
    return true
  }
  return Array.isArray(value) && value.every((item) => isPrimitiveOutputValue(item))
}

function formatOutputSummaryValue(value) {
  if (value == null) {
    return '-'
  }
  if (Array.isArray(value)) {
    return value.length > 0 ? value.map((item) => formatOutputSummaryValue(item)).join('\n') : '-'
  }
  if (typeof value === 'string') {
    return value
  }
  return String(value)
}

function asRecord(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {}
  }
  return value
}

function asRecordList(value) {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter((item) => item && typeof item === 'object' && !Array.isArray(item))
}

function asList(value) {
  return Array.isArray(value) ? value : []
}

function asNonNegativeInt(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0
}

function asPositiveIntOrNull(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function parseJsonRecord(rawJson) {
  const rawText = String(rawJson || '').trim()
  if (!rawText || !rawText.startsWith('{')) {
    return {}
  }
  try {
    const parsed = JSON.parse(rawText)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

function appendCollectionValues(target, seen, value) {
  if (typeof value === 'string') {
    const cleaned = value.trim()
    if (cleaned && !seen.has(cleaned)) {
      seen.add(cleaned)
      target.push(cleaned)
    }
    return
  }
  if (!Array.isArray(value)) {
    return
  }
  for (const item of value) {
    appendCollectionValues(target, seen, item)
  }
}

function collectLegacyCollections({ promptPayload, quickContext, outputPayload }) {
  const collections = []
  const seen = new Set()
  appendCollectionValues(collections, seen, quickContext.collection)
  appendCollectionValues(collections, seen, quickContext.collections)
  appendCollectionValues(collections, seen, promptPayload.collections)
  appendCollectionValues(collections, seen, promptPayload.selected_collections)
  const taskContext = asRecord(promptPayload.task_context)
  const flowchartContext = asRecord(taskContext.flowchart)
  const ragQuick = asRecord(taskContext.rag_quick_run)
  appendCollectionValues(collections, seen, flowchartContext.collections)
  appendCollectionValues(collections, seen, ragQuick.collection)
  appendCollectionValues(collections, seen, ragQuick.collections)
  appendCollectionValues(collections, seen, asRecord(flowchartContext.node_config).collections)
  appendCollectionValues(collections, seen, asRecord(promptPayload.node_config).collections)
  appendCollectionValues(collections, seen, asRecord(promptPayload.flowchart_node_config).collections)
  appendCollectionValues(collections, seen, outputPayload.collections)
  appendCollectionValues(collections, seen, outputPayload.selected_collections)
  appendCollectionValues(collections, seen, asRecord(outputPayload.quick_rag).collection)
  appendCollectionValues(collections, seen, asRecord(outputPayload.quick_rag).collections)
  return collections
}

function legacyConnectorBlocks(incomingConnectorContext) {
  const triggerNodes = asRecordList(incomingConnectorContext.upstream_nodes)
  const contextOnlyNodes = asRecordList(incomingConnectorContext.dotted_upstream_nodes)
  const blocks = []
  for (const [index, node] of triggerNodes.entries()) {
    blocks.push({
      id: `trigger-${index + 1}`,
      label: String(node.condition_key || `Trigger connector ${index + 1}`),
      classification: 'trigger',
      source_node_id: node.source_node_id,
      source_node_type: node.source_node_type,
      condition_key: node.condition_key,
      edge_mode: node.edge_mode,
      output_state: node.output_state,
    })
  }
  for (const [index, node] of contextOnlyNodes.entries()) {
    blocks.push({
      id: `context-only-${index + 1}`,
      label: String(node.condition_key || `Context only connector ${index + 1}`),
      classification: 'context_only',
      source_node_id: node.source_node_id,
      source_node_type: node.source_node_type,
      condition_key: node.condition_key,
      edge_mode: node.edge_mode,
      output_state: node.output_state,
    })
  }
  return blocks
}

function legacyResultsPrimaryText(summaryItems, outputPayload, outputText, outputIsJson) {
  for (const key of OUTPUT_SUMMARY_PREFERRED_KEYS) {
    const value = outputPayload[key]
    if (typeof value === 'string' && value.trim()) {
      return value.trim()
    }
  }
  const actionResultsValue = outputPayload.action_results
  if (Array.isArray(actionResultsValue)) {
    const first = actionResultsValue.find((item) => typeof item === 'string' && item.trim())
    if (first) {
      return first.trim()
    }
  }
  const firstSummaryValue = summaryItems.find(
    (item) => typeof item.value === 'string' && item.value.trim(),
  )
  if (firstSummaryValue) {
    return firstSummaryValue.value.trim()
  }
  if (!outputIsJson && outputText.trim()) {
    return outputText.trim()
  }
  return ''
}

function stageEntryLabel(stage, index) {
  const label = String(stage?.label || '').trim()
  if (label) {
    return label
  }
  const key = String(stage?.key || '').trim()
  if (key) {
    return key
  }
  return `Stage ${index + 1}`
}

export function buildNodeLeftPanelSections(leftPanel) {
  const panel = asRecord(leftPanel)
  return NODE_LEFT_SECTION_DEFINITIONS.map((section) => ({
    ...section,
    value: asRecord(panel[section.key]),
  }))
}

export function resolveNodeLeftPanelPayload(payload) {
  const payloadRecord = asRecord(payload)
  const task = asRecord(payloadRecord.task)
  const outputText = String(task.output || '')
  const outputPresentation = presentNodeOutput(outputText)
  const outputPayload = parseJsonRecord(outputText)
  const promptPayload = parseJsonRecord(payloadRecord.prompt_json)
  const incomingConnectorContext = asRecord(payloadRecord.incoming_connector_context)
  const connectorBlocks = legacyConnectorBlocks(incomingConnectorContext)

  const summaryRows = outputPresentation.summaryItems.map((item) => ({
    key: item.key,
    label: item.label,
    value: item.value,
  }))
  const actionResultsValue = outputPayload.action_results
  const actionResults = Array.isArray(actionResultsValue)
    ? actionResultsValue.map((item) => String(item || '').trim()).filter((item) => item)
    : typeof actionResultsValue === 'string' && actionResultsValue.trim()
      ? [actionResultsValue.trim()]
      : []
  const primaryText = legacyResultsPrimaryText(
    outputPresentation.summaryItems,
    outputPayload,
    outputText,
    outputPresentation.isJson,
  )

  const agent = asRecord(payloadRecord.agent)
  const agentId = asPositiveIntOrNull(agent.id)
  const mcpServers = asRecordList(payloadRecord.mcp_servers).map((server) => ({
    id: asPositiveIntOrNull(server.id),
    name: String(server.name || ''),
    server_key: String(server.server_key || ''),
  }))

  const collections = collectLegacyCollections({
    promptPayload,
    quickContext: asRecord(payloadRecord.quick_context),
    outputPayload,
  })

  const detailRows = LEGACY_DETAIL_BASE_FIELDS.map(([key, label]) => ({
    key,
    label,
    value: task[key] == null || task[key] === '' ? '-' : task[key],
  }))
  for (const detailItem of outputPresentation.detailMetadataItems) {
    detailRows.push({
      key: detailItem.key,
      label: detailItem.label,
      value: detailItem.value,
    })
  }

  return {
    input: {
      source: String(incomingConnectorContext.source || 'none'),
      trigger_source_count: asNonNegativeInt(
        incomingConnectorContext.trigger_source_count ?? asList(incomingConnectorContext.trigger_sources).length,
      ),
      context_only_source_count: asNonNegativeInt(
        incomingConnectorContext.context_only_source_count
        ?? incomingConnectorContext.pulled_dotted_source_count
        ?? asList(incomingConnectorContext.context_only_sources).length,
      ),
      connector_blocks: connectorBlocks,
      resolved_input_context: asRecord(incomingConnectorContext.input_context),
    },
    results: {
      summary_rows: summaryRows,
      primary_text: primaryText,
      action_results: actionResults,
    },
    prompt: {
      provided_prompt_text: String(payloadRecord.prompt_text || ''),
      provided_prompt_fields: promptPayload,
      no_inferred_prompt_in_deterministic_mode: false,
      notice: '',
    },
    agent: {
      id: agentId,
      name: String(agent.name || ''),
      link_href: agentId ? `/agents/${agentId}` : '',
    },
    mcp_servers: {
      items: mcpServers,
    },
    collections: {
      items: collections.map((name) => ({
        id_or_key: name,
        name,
      })),
    },
    raw_json: {
      formatted_output: outputPresentation.formattedText,
      is_json: outputPresentation.isJson,
    },
    details: {
      rows: detailRows,
    },
  }
}

export function inputConnectorSummaryRows(value) {
  const input = asRecord(value)
  const connectorBlocks = asRecordList(input.connector_blocks)
  return [
    { label: 'Context source', value: String(input.source || '-') },
    { label: 'Trigger incoming connectors', value: asNonNegativeInt(input.trigger_source_count) },
    { label: 'Context only incoming connectors', value: asNonNegativeInt(input.context_only_source_count) },
    { label: 'Connector blocks', value: connectorBlocks.length },
  ]
}

export function connectorOutputRows(outputState) {
  const output = asRecord(outputState)
  const rows = []
  for (const [key, value] of Object.entries(output)) {
    if (!isSummaryOutputValue(value)) {
      continue
    }
    rows.push({
      key,
      label: key.replaceAll('_', ' '),
      value: formatOutputSummaryValue(value),
    })
  }
  return rows
}

export function nodeHistoryHref(task) {
  const flowchartNodeId = Number.parseInt(String(task?.flowchart_node_id || ''), 10)
  if (Number.isInteger(flowchartNodeId) && flowchartNodeId > 0) {
    return `/nodes?flowchart_node_id=${flowchartNodeId}`
  }
  return '/nodes'
}

export function stageLogEmptyMessage(stage, index) {
  const label = stageEntryLabel(stage, index).trim().toLowerCase()
  if (label === 'rag indexing' || label === 'rag delta indexing') {
    return 'Waiting for indexing logs...'
  }
  return 'No logs yet.'
}

export function presentNodeOutput(rawOutput) {
  const text = String(rawOutput || '')
  if (!text.trim()) {
    return {
      formattedText: '',
      summaryItems: [],
      detailMetadataItems: [],
      isJson: false,
    }
  }
  try {
    const parsed = JSON.parse(text)
    const formattedText = JSON.stringify(parsed, null, 2)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {
        formattedText,
        summaryItems: [],
        detailMetadataItems: [],
        isJson: true,
      }
    }
    const record = parsed
    const summaryItems = []
    const detailMetadataItems = []
    const detailMetadataKeys = new Set(OUTPUT_DETAIL_METADATA_KEYS)

    for (const key of OUTPUT_DETAIL_METADATA_KEYS) {
      if (!Object.prototype.hasOwnProperty.call(record, key)) {
        continue
      }
      const value = record[key]
      if (!isSummaryOutputValue(value)) {
        continue
      }
      detailMetadataItems.push({
        key,
        label: key.replaceAll('_', ' '),
        value: formatOutputSummaryValue(value),
      })
    }

    for (const key of OUTPUT_SUMMARY_PREFERRED_KEYS) {
      if (!Object.prototype.hasOwnProperty.call(record, key)) {
        continue
      }
      const value = record[key]
      if (detailMetadataKeys.has(key) || !isSummaryOutputValue(value)) {
        continue
      }
      summaryItems.push({
        key,
        label: key.replaceAll('_', ' '),
        value: formatOutputSummaryValue(value),
      })
    }
    return {
      formattedText,
      summaryItems,
      detailMetadataItems,
      isJson: true,
    }
  } catch {
    return {
      formattedText: text,
      summaryItems: [],
      detailMetadataItems: [],
      isJson: false,
    }
  }
}
