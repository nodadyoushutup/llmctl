import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import FlashProvider from '../components/FlashProvider'
import ScriptsPage from './ScriptsPage'
import { deleteScript, getScripts } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  deleteScript: vi.fn(),
  getScripts: vi.fn(),
}))

const SCRIPT_ROWS = [
  { id: 1, file_name: 'pre-init.sh', script_type: 'pre_init', script_type_label: 'Pre-Init Script', description: 'pre init' },
  { id: 2, file_name: 'init.sh', script_type: 'init', script_type_label: 'Init Script', description: 'init' },
  { id: 3, file_name: 'post-init.sh', script_type: 'post_init', script_type_label: 'Post-Init Script', description: 'post init' },
  { id: 4, file_name: 'post-run.sh', script_type: 'post_run', script_type_label: 'Post-Autorun Script', description: 'post run' },
]

function renderPage(initialEntry = '/scripts?script_type=init') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <FlashProvider>
        <Routes>
          <Route path="/scripts" element={<ScriptsPageRouteProbe />} />
          <Route path="/scripts/new" element={<p>New script route</p>} />
          <Route path="/scripts/:scriptId" element={<p>Script detail route</p>} />
        </Routes>
      </FlashProvider>
    </MemoryRouter>,
  )
}

function ScriptsPageRouteProbe() {
  const location = useLocation()
  return (
    <>
      <ScriptsPage />
      <p data-testid="scripts-route-search">{location.search}</p>
    </>
  )
}

describe('ScriptsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getScripts.mockResolvedValue({
      scripts: SCRIPT_ROWS,
      script_types: [
        { value: 'pre_init', label: 'Pre-Init Script' },
        { value: 'init', label: 'Init Script' },
        { value: 'post_init', label: 'Post-Init Script' },
        { value: 'post_run', label: 'Post-Autorun Script' },
      ],
    })
    deleteScript.mockResolvedValue({ ok: true })
  })

  test('renders script-type side nav and filters rows by selected script type', async () => {
    renderPage('/scripts?script_type=init')
    expect(await screen.findByRole('link', { name: 'init.sh' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'pre-init.sh' })).not.toBeInTheDocument()

    expect(screen.getByRole('link', { name: /^Pre Init$/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /^Init$/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /^Post Init$/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /^Post Run$/i })).toBeInTheDocument()
  })

  test('places pagination controls in header actions and updates query params', async () => {
    renderPage('/scripts?script_type=init')
    await screen.findByRole('link', { name: 'init.sh' })

    expect(screen.getByLabelText('Scripts pages')).toBeInTheDocument()
    expect(screen.getByLabelText('Rows per page')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Rows per page'), { target: { value: '10' } })
    await waitFor(() => {
      expect(screen.getByTestId('scripts-route-search')).toHaveTextContent('per_page=10')
    })
  })

  test('new script action remains in header and routes correctly', async () => {
    renderPage('/scripts?script_type=init')
    await screen.findByRole('link', { name: 'init.sh' })
    fireEvent.click(screen.getByRole('link', { name: 'New script' }))
    expect(await screen.findByText('New script route')).toBeInTheDocument()
  })
})
