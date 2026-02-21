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

function asNonNegativeInt(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0
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
