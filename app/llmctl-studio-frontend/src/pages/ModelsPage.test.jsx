import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import FlashProvider from '../components/FlashProvider'
import ModelsPage from './ModelsPage'
import { deleteModel, getModels, updateDefaultModel } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  deleteModel: vi.fn(),
  getModels: vi.fn(),
  updateDefaultModel: vi.fn(),
}))

function renderPage(initialEntry = '/models') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <FlashProvider>
        <Routes>
          <Route path="/models" element={<ModelsPageRouteProbe />} />
          <Route path="/models/new" element={<p>New model route</p>} />
          <Route path="/models/:modelId/edit" element={<ModelEditRouteProbe />} />
          <Route path="/models/:modelId" element={<ModelDetailRouteProbe />} />
        </Routes>
      </FlashProvider>
    </MemoryRouter>,
  )
}

function ModelsPageRouteProbe() {
  const location = useLocation()
  return (
    <>
      <ModelsPage />
      <p data-testid="models-route-search">{location.search}</p>
    </>
  )
}

function ModelDetailRouteProbe() {
  const location = useLocation()
  return (
    <>
      <p>Model detail route</p>
      <p data-testid="model-detail-from">{String(location.state?.from || '')}</p>
    </>
  )
}

function ModelEditRouteProbe() {
  const location = useLocation()
  return (
    <>
      <p>Model edit route</p>
      <p data-testid="model-edit-from">{String(location.state?.from || '')}</p>
    </>
  )
}

const MODEL_ROWS = [
  {
    id: 11,
    name: 'Beta',
    description: 'Second model',
    provider: 'codex',
    provider_label: 'Codex',
    model_name: 'gpt-5-codex',
    is_default: false,
    capability_tags: ['coding', 'reasoning'],
  },
  {
    id: 7,
    name: 'Alpha',
    description: 'First model',
    provider: 'claude',
    provider_label: 'Claude',
    model_name: 'claude-4',
    is_default: true,
    capability_tags: ['authoring', 'analysis', 'planning', 'review'],
  },
  {
    id: 22,
    name: 'Gamma',
    description: 'Third model',
    provider: 'gemini',
    provider_label: 'Gemini',
    model_name: 'gemini-2.0',
    is_default: false,
    capability_tags: ['research'],
  },
]

function setViewportNarrow(matches) {
  const listeners = new Set()
  window.matchMedia = vi.fn().mockImplementation(() => ({
    matches,
    media: '(max-width: 980px)',
    onchange: null,
    addListener: (listener) => listeners.add(listener),
    removeListener: (listener) => listeners.delete(listener),
    addEventListener: (_event, listener) => listeners.add(listener),
    removeEventListener: (_event, listener) => listeners.delete(listener),
    dispatchEvent: () => true,
  }))
}

describe('ModelsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.sessionStorage.clear()
    window.scrollTo = vi.fn()
    setViewportNarrow(false)
    getModels.mockResolvedValue({
      models: MODEL_ROWS,
      default_model_id: 7,
    })
    deleteModel.mockResolvedValue({ ok: true })
    updateDefaultModel.mockResolvedValue({ ok: true })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  test('respects query-driven filter and sorting state', async () => {
    const { container } = renderPage('/models?provider=codex&sort=name&dir=asc')

    await waitFor(() => {
      expect(getModels).toHaveBeenCalledTimes(1)
    })

    expect(await screen.findByRole('link', { name: 'Beta' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Alpha' })).not.toBeInTheDocument()
    const row = container.querySelector('tr.table-row-link')
    expect(row?.getAttribute('data-href')).toBe('/models/11')
  })

  test('renders default model-management list columns and header create action', async () => {
    renderPage('/models')
    await screen.findByRole('link', { name: 'Alpha' })
    expect(screen.getByRole('columnheader', { name: 'Name' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Provider' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Default Alias' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Capability Tags' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Actions' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'New model' })).toBeInTheDocument()
  })

  test('debounces search updates before filtering table rows', async () => {
    renderPage('/models?per_page=10')
    await screen.findByRole('link', { name: 'Alpha' })

    const searchInput = screen.getByLabelText('Search')
    fireEvent.change(searchInput, { target: { value: 'Gamma' } })

    expect(screen.getByRole('link', { name: 'Alpha' })).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.queryByRole('link', { name: 'Alpha' })).not.toBeInTheDocument()
    })
    expect(screen.getByRole('link', { name: 'Gamma' })).toBeInTheDocument()
  })

  test('renders panel-scoped skeleton rows while the list is loading', async () => {
    let resolveModels
    const pendingModels = new Promise((resolve) => {
      resolveModels = resolve
    })
    getModels.mockReturnValueOnce(pendingModels)

    renderPage('/models')

    expect(await screen.findByTestId('models-loading-skeleton')).toBeInTheDocument()
    expect(screen.getAllByTestId('models-skeleton-row')).toHaveLength(5)

    resolveModels({ models: MODEL_ROWS, default_model_id: 7 })
    expect(await screen.findByRole('link', { name: 'Alpha' })).toBeInTheDocument()
  })

  test('renders inline initial-load error state with retry action', async () => {
    getModels.mockRejectedValueOnce(new Error('Initial load failed in test'))
    getModels.mockResolvedValueOnce({
      models: MODEL_ROWS,
      default_model_id: 7,
    })

    renderPage('/models')

    expect(await screen.findByText('Initial load failed in test')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))

    await waitFor(() => {
      expect(getModels).toHaveBeenCalledTimes(2)
    })
    expect(await screen.findByRole('link', { name: 'Alpha' })).toBeInTheDocument()
  })

  test('clicking a non-interactive row area navigates to model detail', async () => {
    const { container } = renderPage('/models')
    await screen.findByRole('link', { name: 'Alpha' })

    const row = container.querySelector('tr.table-row-link')
    const rowCell = row?.querySelector('td')
    expect(rowCell).toBeTruthy()
    fireEvent.click(rowCell)
    expect(await screen.findByText('Model detail route')).toBeInTheDocument()
    expect(screen.getByTestId('model-detail-from')).toHaveTextContent('/models')
  })

  test('pressing Enter on a focused row navigates to model detail', async () => {
    const { container } = renderPage('/models')
    await screen.findByRole('link', { name: 'Alpha' })
    const row = container.querySelector('tr.table-row-link')
    expect(row).toBeTruthy()
    row?.focus()
    fireEvent.keyDown(row, { key: 'Enter' })
    expect(await screen.findByText('Model detail route')).toBeInTheDocument()
  })

  test('delete icon action does not trigger row navigation', async () => {
    renderPage('/models')
    await screen.findByRole('link', { name: 'Alpha' })
    fireEvent.click(screen.getAllByRole('button', { name: 'Delete model' })[0])
    expect(deleteModel).not.toHaveBeenCalled()
    expect(screen.getAllByRole('button', { name: 'Confirm delete model' })).toHaveLength(1)
    expect(screen.queryByText('Model detail route')).not.toBeInTheDocument()
  })

  test('operation failures report through flash viewport instead of inline error text', async () => {
    deleteModel.mockRejectedValueOnce(new Error('Delete failed in test'))

    renderPage('/models')
    await screen.findByRole('link', { name: 'Alpha' })
    fireEvent.click(screen.getAllByRole('button', { name: 'Delete model' })[0])
    fireEvent.click(screen.getAllByRole('button', { name: 'Confirm delete model' })[0])

    expect(await screen.findByText('Delete failed in test')).toBeInTheDocument()
    expect(screen.queryByText('Delete failed in test', { selector: 'p.error-text' })).not.toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'Delete model' })).toHaveLength(3)
    })
    expect(screen.queryByRole('button', { name: 'Confirm delete model' })).not.toBeInTheDocument()
  })

  test('create action uses routed page transition to /models/new', async () => {
    renderPage('/models')
    await screen.findByRole('link', { name: 'Alpha' })
    fireEvent.click(screen.getByRole('link', { name: 'New model' }))
    expect(await screen.findByText('New model route')).toBeInTheDocument()
  })

  test('search changes reset pagination to first page', async () => {
    const manyModels = Array.from({ length: 12 }, (_, index) => ({
      id: index + 1,
      name: `Model ${index + 1}`,
      description: index === 11 ? 'Focus target' : `Model ${index + 1} description`,
      provider: 'codex',
      provider_label: 'Codex',
      model_name: `model-${index + 1}`,
      is_default: index === 0,
    }))
    getModels.mockResolvedValueOnce({ models: manyModels, default_model_id: 1 })
    renderPage('/models?page=2&per_page=10')
    await screen.findByRole('link', { name: 'Model 8' })
    expect(screen.getByTestId('models-route-search')).toHaveTextContent('?page=2&per_page=10')

    fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'Focus target' } })

    await waitFor(() => {
      expect(screen.getByRole('link', { name: 'Model 12' })).toBeInTheDocument()
      expect(screen.queryByRole('link', { name: 'Model 8' })).not.toBeInTheDocument()
      const search = screen.getByTestId('models-route-search').textContent || ''
      expect(search).toContain('q=Focus+target')
      expect(search).not.toContain('page=2')
    })
  })

  test('row navigation preserves full list query state for detail/back links', async () => {
    const initialSearch = '?page=2&per_page=1&provider=codex&sort=provider&dir=desc&q=be'
    const { container } = renderPage(`/models${initialSearch}`)
    await screen.findByRole('link', { name: 'Beta' })

    const row = container.querySelector('tr.table-row-link')
    const rowCell = row?.querySelector('td')
    expect(rowCell).toBeTruthy()
    fireEvent.click(rowCell)

    expect(await screen.findByText('Model detail route')).toBeInTheDocument()
    expect(screen.getByTestId('model-detail-from')).toHaveTextContent(`/models${initialSearch}`)
  })

  test('restores saved scroll offset when returning with matching list query', async () => {
    const requestAnimationFrameSpy = vi
      .spyOn(window, 'requestAnimationFrame')
      .mockImplementation((callback) => {
        callback(0)
        return 0
      })
    window.sessionStorage.setItem('llmctl:models:list:scroll:query', '?provider=codex')
    window.sessionStorage.setItem('llmctl:models:list:scroll', '240')

    renderPage('/models?provider=codex')
    await screen.findByRole('link', { name: 'Beta' })

    await waitFor(() => {
      expect(window.scrollTo).toHaveBeenCalledWith({ top: 240, behavior: 'auto' })
    })
    expect(window.sessionStorage.getItem('llmctl:models:list:scroll')).toBeNull()
    expect(window.sessionStorage.getItem('llmctl:models:list:scroll:query')).toBeNull()
    requestAnimationFrameSpy.mockRestore()
  })

  test('empty-state includes a primary New Model action in the body', async () => {
    getModels.mockResolvedValueOnce({ models: [], default_model_id: null })
    renderPage('/models')
    expect(await screen.findByText('No models matched the current filters.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: 'New Model' }))
    expect(await screen.findByText('New model route')).toBeInTheDocument()
  })

  test('places pagination controls in the right-side list header controls', async () => {
    renderPage('/models')
    await screen.findByRole('link', { name: 'Alpha' })
    expect(screen.getByTestId('models-list-controls')).toBeInTheDocument()
    expect(screen.getByLabelText('Models pages')).toBeInTheDocument()
    expect(screen.getByLabelText('Rows per page')).toBeInTheDocument()
  })

  test('defaults to 25 rows per page and name ascending when query params are omitted', async () => {
    const manyModels = Array.from({ length: 30 }, (_, index) => ({
      id: index + 1,
      name: `Model ${String(index + 1).padStart(2, '0')}`,
      description: `Model ${index + 1} description`,
      provider: 'codex',
      provider_label: 'Codex',
      model_name: `model-${index + 1}`,
      is_default: index === 0,
      capability_tags: [],
    }))
    getModels.mockResolvedValueOnce({ models: manyModels, default_model_id: 1 })

    renderPage('/models')

    expect(await screen.findByRole('link', { name: 'Model 01' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Model 25' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Model 26' })).not.toBeInTheDocument()
    expect(screen.getByText('/ 2')).toBeInTheDocument()
  })

  test('surfaces compatibility drift notice through flash and exposes review settings hint', async () => {
    getModels.mockResolvedValueOnce({
      models: [
        {
          ...MODEL_ROWS[0],
          compatibility: { drift_detected: true, missing_keys: ['project'] },
        },
        {
          ...MODEL_ROWS[1],
          compatibility: { drift_detected: false, missing_keys: [] },
        },
      ],
      default_model_id: 7,
      compatibility_summary: {
        drifted_count: 1,
        in_sync_count: 1,
      },
    })

    renderPage('/models')

    expect(await screen.findByText('1 model profile needs review settings to align with current provider capabilities.')).toBeInTheDocument()
    const reviewLink = screen.getByRole('link', { name: 'Review settings' })
    fireEvent.click(reviewLink)
    expect(await screen.findByText('Model edit route')).toBeInTheDocument()
    expect(screen.getByTestId('model-edit-from')).toHaveTextContent('/models')
  })

  test('uses a Filters popover on narrow screens while keeping search and pagination visible', async () => {
    setViewportNarrow(true)
    renderPage('/models')
    await screen.findByRole('link', { name: 'Alpha' })

    expect(screen.getByLabelText('Search')).toBeInTheDocument()
    expect(screen.getByText('Filters')).toBeInTheDocument()
    expect(screen.getByLabelText('Models pages')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'New model' })).toBeInTheDocument()

    fireEvent.click(screen.getByText('Filters'))
    expect(screen.getByLabelText('Provider')).toBeInTheDocument()
    expect(screen.getByLabelText('Sort')).toBeInTheDocument()
  })

  test('renders capability overflow as +N with hover title and tap popover', async () => {
    renderPage('/models')
    await screen.findByRole('link', { name: 'Alpha' })

    expect(screen.getByText('authoring')).toBeInTheDocument()
    expect(screen.getByText('analysis')).toBeInTheDocument()
    expect(screen.queryByText('planning, review')).not.toBeInTheDocument()

    const overflowButton = screen.getByRole('button', { name: 'Show 2 more capability tags' })
    expect(overflowButton).toHaveAttribute('title', 'authoring, analysis, planning, review')

    fireEvent.click(overflowButton)
    expect(screen.getByText('planning, review')).toBeInTheDocument()

    fireEvent.click(overflowButton)
    expect(screen.queryByText('planning, review')).not.toBeInTheDocument()
  })
})
