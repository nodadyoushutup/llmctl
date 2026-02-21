import { describe, expect, test } from 'vitest'
import {
  buildNodeLeftPanelSections,
  connectorOutputRows,
  inputConnectorSummaryRows,
  NODE_LEFT_DEFAULT_SECTION_KEY,
  nodeHistoryHref,
  presentNodeOutput,
  resolveNodeLeftPanelPayload,
  stageLogEmptyMessage,
} from './NodeDetailPage.helpers'

describe('NodeDetailPage stage log empty state', () => {
  test('shows indexing wait message for rag indexing stage label', () => {
    expect(stageLogEmptyMessage({ label: 'RAG Indexing' }, 0)).toBe('Waiting for indexing logs...')
  })

  test('shows indexing wait message for rag delta indexing stage label', () => {
    expect(stageLogEmptyMessage({ label: 'RAG Delta Indexing' }, 0)).toBe('Waiting for indexing logs...')
  })

  test('falls back to generic empty stage message for non-indexing labels', () => {
    expect(stageLogEmptyMessage({ label: 'LLM Query' }, 0)).toBe('No logs yet.')
  })
})

describe('NodeDetailPage node history link', () => {
  test('uses flowchart node id when available', () => {
    expect(nodeHistoryHref({ flowchart_node_id: 17 })).toBe('/nodes?flowchart_node_id=17')
  })

  test('falls back to all nodes when flowchart node id is missing', () => {
    expect(nodeHistoryHref({})).toBe('/nodes')
  })
})

describe('NodeDetailPage output presentation', () => {
  test('pretty-prints JSON output and separates summary from detail metadata fields', () => {
    const output = presentNodeOutput('{"node_type":"memory","action":"add","message":"stored","action_results":["one","two"]}')
    expect(output.isJson).toBe(true)
    expect(output.formattedText).toContain('\n  "node_type": "memory"')
    expect(output.summaryItems).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: 'message', value: 'stored' }),
        expect.objectContaining({ key: 'action_results', value: 'one\ntwo' }),
      ]),
    )
    expect(output.summaryItems).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ key: 'node_type' }),
      expect.objectContaining({ key: 'action' }),
    ]))
    expect(output.detailMetadataItems).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: 'node_type', value: 'memory' }),
        expect.objectContaining({ key: 'action', value: 'add' }),
      ]),
    )
  })

  test('returns raw text when output is not JSON', () => {
    const output = presentNodeOutput('plain text output')
    expect(output.isJson).toBe(false)
    expect(output.formattedText).toBe('plain text output')
    expect(output.summaryItems).toEqual([])
    expect(output.detailMetadataItems).toEqual([])
  })
})

describe('NodeDetailPage left panel view model', () => {
  test('uses frozen section order and default expanded key', () => {
    const sections = buildNodeLeftPanelSections({})
    expect(sections.map((section) => section.key)).toEqual([
      'input',
      'results',
      'prompt',
      'agent',
      'mcp_servers',
      'collections',
      'raw_json',
      'details',
    ])
    expect(NODE_LEFT_DEFAULT_SECTION_KEY).toBe('results')
  })

  test('attaches frozen empty-state messages for all sections', () => {
    const sectionByKey = Object.fromEntries(
      buildNodeLeftPanelSections({}).map((section) => [section.key, section]),
    )
    expect(sectionByKey.input.emptyMessage).toBe('No incoming connector context captured for this node run.')
    expect(sectionByKey.results.emptyMessage).toBe('No results yet.')
    expect(sectionByKey.prompt.emptyMessage).toBe('No prompt recorded.')
    expect(sectionByKey.agent.emptyMessage).toBe('No agent recorded for this node.')
    expect(sectionByKey.mcp_servers.emptyMessage).toBe('No MCP servers selected.')
    expect(sectionByKey.collections.emptyMessage).toBe('No collections selected.')
    expect(sectionByKey.raw_json.emptyMessage).toBe('No output yet.')
    expect(sectionByKey.details.emptyMessage).toBe('No details yet.')
  })

  test('builds left panel from canonical node payload fields', () => {
    const panel = resolveNodeLeftPanelPayload({
      task: {
        id: 469,
        kind: 'task',
        flowchart_id: 1,
        flowchart_run_id: 82,
        flowchart_node_id: 13,
        model_id: 7,
        run_task_id: 29,
        celery_task_id: 'abc-123',
        current_stage: 'post_autorun',
        status: 'succeeded',
        created_at: '2026-02-21 20:52:20',
        started_at: '2026-02-21 20:52:22',
        finished_at: '2026-02-21 20:52:28',
        output: '{"message":"Stored summary","action":"add","action_results":["Added memory."]}',
      },
      prompt_text: 'Summarize and store this.',
      prompt_json: '{"collections":["engineering-notes"]}',
      incoming_connector_context: {
        source: 'flowchart_run_node',
        input_context: { upstream_nodes: [{ source_node_id: 2 }] },
        upstream_nodes: [
          {
            source_node_id: 2,
            source_node_type: 'task',
            condition_key: 'success',
            edge_mode: 'solid',
            output_state: { message: 'ok' },
          },
        ],
        dotted_upstream_nodes: [],
        trigger_source_count: 1,
        context_only_source_count: 0,
      },
      mcp_servers: [{ id: 3, name: 'Memory', server_key: 'llmctl-memory' }],
      agent: { id: 5, name: 'Project Manager' },
      quick_context: { collection: 'engineering-notes' },
    })

    expect(panel.results.primary_text).toBe('Stored summary')
    expect(panel.results.summary_rows).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: 'message', value: 'Stored summary' }),
      ]),
    )
    expect(panel.prompt.provided_prompt_text).toBe('Summarize and store this.')
    expect(panel.agent.link_href).toBe('/agents/5')
    expect(panel.input.connector_blocks).toHaveLength(1)
    expect(panel.raw_json.is_json).toBe(true)
    expect(panel.collections.items).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: 'engineering-notes' }),
      ]),
    )
    expect(panel.details.rows).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: 'status', value: 'succeeded' }),
        expect.objectContaining({ key: 'action', value: 'add' }),
      ]),
    )
  })
})

describe('NodeDetailPage connector context helpers', () => {
  test('builds connector summary rows from input section payload', () => {
    const rows = inputConnectorSummaryRows({
      source: 'flowchart_run_node',
      trigger_source_count: 2,
      context_only_source_count: 3,
      connector_blocks: [{ id: 'a' }, { id: 'b' }],
    })
    expect(rows).toEqual([
      { label: 'Context source', value: 'flowchart_run_node' },
      { label: 'Trigger incoming connectors', value: 2 },
      { label: 'Context only incoming connectors', value: 3 },
      { label: 'Connector blocks', value: 2 },
    ])
  })

  test('extracts structured connector output rows for primitive/array values only', () => {
    const rows = connectorOutputRows({
      name: 'James',
      score: 9,
      flags: ['one', 'two'],
      nested: { should: 'skip' },
    })
    expect(rows).toEqual([
      { key: 'name', label: 'name', value: 'James' },
      { key: 'score', label: 'score', value: '9' },
      { key: 'flags', label: 'flags', value: 'one\ntwo' },
    ])
  })
})
