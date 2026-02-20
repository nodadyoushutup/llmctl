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

  test('chat launch route is native react', async () => {
    renderAt('/chat')
    expect(await screen.findByRole('button', { name: 'Create thread' })).toBeInTheDocument()
  })

  test('chat activity route is native react', async () => {
    renderAt('/chat/activity')
    expect(await screen.findByText('Thread lifecycle, turn, retrieval/tool, compaction, and failure audit events.')).toBeInTheDocument()
  })

  test('nodes route is native react', async () => {
    renderAt('/nodes')
    expect((await screen.findAllByRole('heading', { name: 'Nodes' })).length).toBeGreaterThan(0)
  })

  test('plans route is native react', async () => {
    renderAt('/plans')
    expect((await screen.findAllByRole('heading', { name: 'Plans' })).length).toBeGreaterThan(0)
  })

  test('artifacts route is native react', async () => {
    renderAt('/artifacts/type/task')
    expect(await screen.findByRole('heading', { name: 'Task Artifacts' })).toBeInTheDocument()
  })

  test('milestones route is native react', async () => {
    renderAt('/milestones')
    expect((await screen.findAllByRole('heading', { name: 'Milestones' })).length).toBeGreaterThan(0)
  })

  test('memories route is native react', async () => {
    renderAt('/memories')
    expect((await screen.findAllByRole('heading', { name: 'Memories' })).length).toBeGreaterThan(0)
  })

  test('flowcharts route is native react', async () => {
    renderAt('/flowcharts')
    expect(await screen.findByRole('link', { name: 'New flowchart' })).toBeInTheDocument()
  })

  test('skills route is native react', async () => {
    renderAt('/skills')
    expect((await screen.findAllByRole('heading', { name: 'Skills' })).length).toBeGreaterThan(0)
  })

  test('scripts route is native react', async () => {
    renderAt('/scripts')
    expect((await screen.findAllByRole('heading', { name: 'Scripts' })).length).toBeGreaterThan(0)
  })

  test('attachments route is native react', async () => {
    renderAt('/attachments')
    expect((await screen.findAllByRole('heading', { name: 'Attachments' })).length).toBeGreaterThan(0)
  })

  test('models route is native react', async () => {
    renderAt('/models')
    expect((await screen.findAllByRole('heading', { name: 'Models' })).length).toBeGreaterThan(0)
  })

  test('new model route is native react', async () => {
    renderAt('/models/new')
    expect(await screen.findByRole('heading', { name: 'New Model' })).toBeInTheDocument()
  })

  test('model detail route is native react', async () => {
    renderAt('/models/1')
    expect(await screen.findByRole('heading', { name: 'Model' })).toBeInTheDocument()
  })

  test('mcps route is native react', async () => {
    renderAt('/mcps')
    expect((await screen.findAllByRole('heading', { name: 'MCP Servers' })).length).toBeGreaterThan(0)
  })

  test('github route is native react', async () => {
    renderAt('/github')
    expect(await screen.findByRole('heading', { name: 'GitHub Workspace' })).toBeInTheDocument()
  })

  test('jira route is native react', async () => {
    renderAt('/jira')
    expect(await screen.findByRole('heading', { name: 'Jira Workspace' })).toBeInTheDocument()
  })

  test('confluence route is native react', async () => {
    renderAt('/confluence')
    expect(await screen.findByRole('heading', { name: 'Confluence Workspace' })).toBeInTheDocument()
  })

  test('chroma collections route is native react', async () => {
    renderAt('/chroma/collections')
    expect(await screen.findByRole('heading', { name: 'Chroma Collections' })).toBeInTheDocument()
  })

  test('rag chat route redirects to rag sources', async () => {
    renderAt('/rag/chat')
    expect(await screen.findByRole('heading', { name: 'RAG Sources' })).toBeInTheDocument()
  })

  test('rag sources route is native react', async () => {
    renderAt('/rag/sources')
    expect(await screen.findByRole('heading', { name: 'RAG Sources' })).toBeInTheDocument()
  })

  test('settings core route is native react', async () => {
    renderAt('/settings/core')
    expect(await screen.findByRole('heading', { name: 'Core Settings' })).toBeInTheDocument()
  })

  test('settings provider route is native react', async () => {
    renderAt('/settings/provider')
    expect(await screen.findByText('Provider Sections')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /controls/i })).toBeInTheDocument()
  })

  test('settings runtime route is native react', async () => {
    renderAt('/settings/runtime')
    expect(await screen.findByText('Runtime Sections')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /node runtime/i })).toBeInTheDocument()
  })

  test('settings chat route is native react', async () => {
    renderAt('/settings/chat')
    expect(await screen.findByRole('heading', { name: 'Chat Defaults' })).toBeInTheDocument()
  })

  test('settings integrations route is native react', async () => {
    renderAt('/settings/integrations')
    expect(await screen.findByText('Integration Sections')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /^git$/i })).toBeInTheDocument()
  })

  test('unknown route renders react not-found view', async () => {
    renderAt('/does-not-exist')
    expect(await screen.findByText('Route not found')).toBeInTheDocument()
  })
})
