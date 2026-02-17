import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, test } from 'vitest'
import App from './App'

function renderAt(pathname) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <App />
    </MemoryRouter>,
  )
}

describe('App routing', () => {
  test('root route redirects to native overview', async () => {
    renderAt('/')
    expect(await screen.findByText('Track agent density, active load, and the last known autorun signal.')).toBeInTheDocument()
  })

  test('migration route keeps native react migration hub available', async () => {
    renderAt('/migration')
    expect(await screen.findByText('Track agent density, active load, and the last known autorun signal.')).toBeInTheDocument()
    expect(screen.getByText('Newest Agents')).toBeInTheDocument()
  })

  test('agents route is native react', async () => {
    renderAt('/agents')
    expect(await screen.findByText('Open an agent to see its autorun history, connections, and prompt configuration.')).toBeInTheDocument()
  })

  test('runs route is native react', async () => {
    renderAt('/runs')
    expect(await screen.findByText('Autoruns are created automatically when you enable autorun on an agent.')).toBeInTheDocument()
  })

  test('quick route is native react', async () => {
    renderAt('/quick')
    expect(await screen.findByText(/Run one-off prompts with the default Quick Node profile/i)).toBeInTheDocument()
  })

  test('execution monitor route is native react', async () => {
    renderAt('/execution-monitor')
    expect(await screen.findByText('Inspect run and node execution status by id using live API responses.')).toBeInTheDocument()
  })

  test('chat activity route is native react', async () => {
    renderAt('/chat/activity')
    expect(await screen.findByText('Thread lifecycle, turn, retrieval/tool, compaction, and failure audit events.')).toBeInTheDocument()
  })

  test('nodes route is native react', async () => {
    renderAt('/nodes')
    expect(await screen.findByText('Queued, running, and completed node execution records.')).toBeInTheDocument()
  })

  test('plans route is native react', async () => {
    renderAt('/plans')
    expect(await screen.findByText('Track multi-stage plans and task completion with explicit completion timestamps.')).toBeInTheDocument()
  })

  test('milestones route is native react', async () => {
    renderAt('/milestones')
    expect(await screen.findByText('Track delivery checkpoints with ownership, health, and progress.')).toBeInTheDocument()
  })

  test('memories route is native react', async () => {
    renderAt('/memories')
    expect(await screen.findByText('Capture simple facts to reuse across tasks and workflows.')).toBeInTheDocument()
  })

  test('flowcharts route is native react', async () => {
    renderAt('/flowcharts')
    expect(await screen.findByText('Build and run node-based workflows with loops, routing, and guardrails.')).toBeInTheDocument()
  })

  test('skills route is native react', async () => {
    renderAt('/skills')
    expect(await screen.findByText('Native React replacement for `/skills` list plus CRUD/import/export flows.')).toBeInTheDocument()
  })

  test('scripts route is native react', async () => {
    renderAt('/scripts')
    expect(await screen.findByText('Native React replacement for `/scripts` list and row actions.')).toBeInTheDocument()
  })

  test('attachments route is native react', async () => {
    renderAt('/attachments')
    expect(await screen.findByText('Native React replacement for `/attachments` list and row actions.')).toBeInTheDocument()
  })

  test('models route is native react', async () => {
    renderAt('/models')
    expect(await screen.findByText('Native React replacement for `/models` list and default model controls.')).toBeInTheDocument()
  })

  test('mcps route is native react', async () => {
    renderAt('/mcps')
    expect(await screen.findByText('Native React replacement for `/mcps` list/detail/edit flows.')).toBeInTheDocument()
  })

  test('github route is native react', async () => {
    renderAt('/github')
    expect(await screen.findByText('Native React replacement for `/github` browser, pull-request, actions, and code explorer surfaces.')).toBeInTheDocument()
  })

  test('jira route is native react', async () => {
    renderAt('/jira')
    expect(await screen.findByText('Native React replacement for `/jira` board explorer and issue drill-down routes.')).toBeInTheDocument()
  })

  test('confluence route is native react', async () => {
    renderAt('/confluence')
    expect(await screen.findByText('Native React replacement for `/confluence` space browser and page content surfaces.')).toBeInTheDocument()
  })

  test('chroma collections route is native react', async () => {
    renderAt('/chroma/collections')
    expect(await screen.findByText('Native React replacement for `/chroma/collections` explorer, pagination, detail navigation, and delete.')).toBeInTheDocument()
  })

  test('rag chat route is native react', async () => {
    renderAt('/rag/chat')
    expect(await screen.findByText('Native React replacement for `/rag/chat` retrieval chat flow and context controls.')).toBeInTheDocument()
  })

  test('rag sources route is native react', async () => {
    renderAt('/rag/sources')
    expect(await screen.findByText('Native React replacement for `/rag/sources*` list, detail navigation, and quick indexing flows.')).toBeInTheDocument()
  })

  test('settings core route is native react', async () => {
    renderAt('/settings/core')
    expect(await screen.findByText('Native React replacement for `/settings/core` runtime and path metadata.')).toBeInTheDocument()
  })

  test('settings provider route is native react', async () => {
    renderAt('/settings/provider')
    expect(await screen.findByText('Native React replacement for provider controls and auth settings.')).toBeInTheDocument()
  })

  test('settings runtime route is native react', async () => {
    renderAt('/settings/runtime')
    expect(await screen.findByText('Native React replacement for runtime node, RAG, and chat settings flows.')).toBeInTheDocument()
  })

  test('settings chat route is native react', async () => {
    renderAt('/settings/chat')
    expect(await screen.findByText('Native React replacement for `/settings/chat` defaults and runtime values.')).toBeInTheDocument()
  })

  test('settings integrations route is native react', async () => {
    renderAt('/settings/integrations')
    expect(await screen.findByText('Native React replacement for `/settings/integrations/*` configuration and validation controls.')).toBeInTheDocument()
  })

  test('unknown route renders react not-found view', async () => {
    renderAt('/does-not-exist')
    expect(await screen.findByText('Route not found')).toBeInTheDocument()
  })
})
