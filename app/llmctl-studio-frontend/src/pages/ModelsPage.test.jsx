import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
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
          <Route path="/models" element={<ModelsPage />} />
          <Route path="/models/new" element={<p>New model route</p>} />
          <Route path="/models/:modelId" element={<p>Model detail route</p>} />
        </Routes>
      </FlashProvider>
    </MemoryRouter>,
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
  },
  {
    id: 7,
    name: 'Alpha',
    description: 'First model',
    provider: 'claude',
    provider_label: 'Claude',
    model_name: 'claude-4',
    is_default: true,
  },
  {
    id: 22,
    name: 'Gamma',
    description: 'Third model',
    provider: 'gemini',
    provider_label: 'Gemini',
    model_name: 'gemini-2.0',
    is_default: false,
  },
]

describe('ModelsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.sessionStorage.clear()
    window.scrollTo = vi.fn()
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

  test('clicking a non-interactive row area navigates to model detail', async () => {
    const { container } = renderPage('/models')
    await screen.findByRole('link', { name: 'Alpha' })

    const row = container.querySelector('tr.table-row-link')
    const rowCell = row?.querySelector('td')
    expect(rowCell).toBeTruthy()
    fireEvent.click(rowCell)
    expect(await screen.findByText('Model detail route')).toBeInTheDocument()
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
  })

  test('empty-state includes a primary New Model action in the body', async () => {
    getModels.mockResolvedValueOnce({ models: [], default_model_id: null })
    renderPage('/models')
    expect(await screen.findByText('No models matched the current filters.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'New Model' })).toBeInTheDocument()
  })
})
