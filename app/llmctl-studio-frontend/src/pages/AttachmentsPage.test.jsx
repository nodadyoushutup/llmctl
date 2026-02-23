import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import FlashProvider from '../components/FlashProvider'
import AttachmentsPage from './AttachmentsPage'
import { deleteAttachment, getAttachments } from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  deleteAttachment: vi.fn(),
  getAttachments: vi.fn(),
}))

const ATTACHMENTS_BY_SCOPE = {
  chat: [
    {
      id: 1,
      file_name: 'chat-note.txt',
      content_type: 'text/plain',
      size_bytes: 1024,
      chat_binding_count: 2,
      quick_binding_count: 0,
      flowchart_binding_count: 0,
      created_at: '2026-02-22 10:00',
    },
  ],
  quick: [
    {
      id: 2,
      file_name: 'quick-input.json',
      content_type: 'application/json',
      size_bytes: 2048,
      chat_binding_count: 0,
      quick_binding_count: 1,
      flowchart_binding_count: 0,
      created_at: '2026-02-22 10:01',
    },
  ],
  flowchart: [
    {
      id: 3,
      file_name: 'flowchart-state.md',
      content_type: 'text/markdown',
      size_bytes: 4096,
      chat_binding_count: 0,
      quick_binding_count: 0,
      flowchart_binding_count: 3,
      created_at: '2026-02-22 10:02',
    },
  ],
}

function renderPage(initialEntry = '/attachments') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <FlashProvider>
        <Routes>
          <Route path="/attachments" element={<AttachmentsPageRouteProbe />} />
          <Route path="/attachments/:attachmentId" element={<p>Attachment detail route</p>} />
        </Routes>
      </FlashProvider>
    </MemoryRouter>,
  )
}

function AttachmentsPageRouteProbe() {
  const location = useLocation()
  return (
    <>
      <AttachmentsPage />
      <p data-testid="attachments-route-search">{location.search}</p>
    </>
  )
}

describe('AttachmentsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getAttachments.mockImplementation(({ nodeType = 'chat' } = {}) => {
      const rows = ATTACHMENTS_BY_SCOPE[nodeType] || []
      return Promise.resolve({
        items: rows,
        total_count: rows.length,
      })
    })
    deleteAttachment.mockResolvedValue({ ok: true })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  test('renders two-column node-type nav and loads scoped rows', async () => {
    renderPage('/attachments?node_type=quick')
    expect(await screen.findByRole('heading', { name: 'Quick Attachments' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /^Chat$/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /^Quick$/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /^Flowchart$/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'quick-input.json' })).toBeInTheDocument()
    expect(getAttachments).toHaveBeenCalledWith({ nodeType: 'quick', page: 1, perPage: 25 })
  })

  test('renders header pagination controls and updates params from rows-per-page', async () => {
    renderPage('/attachments')
    await screen.findByRole('link', { name: 'chat-note.txt' })
    expect(screen.getByLabelText('Attachments pages')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Rows per page'), { target: { value: '10' } })
    await waitFor(() => {
      expect(screen.getByTestId('attachments-route-search')).toHaveTextContent('per_page=10')
    })
  })
})
