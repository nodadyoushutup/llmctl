import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import ChatPage from './ChatPage'
import {
  archiveChatThread,
  clearChatThread,
  createChatThread,
  getChatThread,
  getChatRuntime,
  sendChatTurn,
  updateChatThreadConfig,
} from '../lib/studioApi'

vi.mock('../lib/studioApi', () => ({
  archiveChatThread: vi.fn(),
  clearChatThread: vi.fn(),
  createChatThread: vi.fn(),
  getChatThread: vi.fn(),
  getChatRuntime: vi.fn(),
  sendChatTurn: vi.fn(),
  updateChatThreadConfig: vi.fn(),
}))

function buildRuntimePayload() {
  return {
    selected_thread_id: 1,
    selected_thread: {
      id: 1,
      title: 'Test thread',
      status: 'active',
      model_id: null,
      model_name: null,
      response_complexity: 'medium',
      response_complexity_label: 'Medium',
      rag_collections: [],
      mcp_servers: [],
      messages: [],
    },
    threads: [
      {
        id: 1,
        title: 'Test thread',
        status: 'active',
        model_id: null,
        model_name: null,
        response_complexity: 'medium',
        response_complexity_label: 'Medium',
        rag_collections: [],
        mcp_servers: [],
      },
    ],
    models: [],
    mcp_servers: [],
    rag_collections: [],
    rag_health: { state: 'configured_healthy', error: '' },
    chat_default_settings: {
      default_model_id: null,
      default_response_complexity: 'medium',
    },
  }
}

function buildThreadPayload(id, title = `Thread ${id}`) {
  return {
    id,
    title,
    status: 'active',
    model_id: null,
    model_name: null,
    response_complexity: 'medium',
    response_complexity_label: 'Medium',
    rag_collections: [],
    mcp_servers: [],
    messages: [],
  }
}

function renderPage(initialEntry = '/chat?thread_id=1') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/chat" element={<ChatPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getChatRuntime.mockResolvedValue(buildRuntimePayload())
    createChatThread.mockResolvedValue({ ok: true, thread: buildThreadPayload(2, 'Thread 2') })
    getChatThread.mockResolvedValue(buildRuntimePayload().selected_thread)
    archiveChatThread.mockResolvedValue({ ok: true })
    clearChatThread.mockResolvedValue({ ok: true, thread: buildRuntimePayload().selected_thread })
    updateChatThreadConfig.mockResolvedValue({ ok: true, thread: buildRuntimePayload().selected_thread })
  })

  test('shows optimistic user message and pending thinking bubble immediately after submit', async () => {
    sendChatTurn.mockImplementation(
      () =>
        new Promise(() => {
          // Keep pending to verify the optimistic in-progress bubble.
        }),
    )

    renderPage()

    await screen.findByRole('button', { name: /send/i })
    const messageInput = screen.getByPlaceholderText('Send a message...')
    fireEvent.change(messageInput, { target: { value: 'hello there' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => {
      expect(sendChatTurn).toHaveBeenCalledWith(1, 'hello there')
    })

    expect(messageInput).toHaveValue('')
    const userBubble = await screen.findByText('hello there')
    expect(userBubble.closest('.chat-message')).toHaveClass('chat-message-user')

    const thinkingBubble = await screen.findByText('Thinking...')
    expect(thinkingBubble).toBeInTheDocument()
    expect(thinkingBubble.closest('.chat-message')).toHaveClass('chat-message-pending')
  })

  test('shows the pending thinking bubble before session-save completes', async () => {
    updateChatThreadConfig.mockImplementation(
      () =>
        new Promise(() => {
          // Keep pending so the submit path remains blocked in session sync.
        }),
    )
    sendChatTurn.mockResolvedValue({ ok: true, thread: buildRuntimePayload().selected_thread })

    renderPage()

    await screen.findByRole('button', { name: /send/i })
    fireEvent.change(screen.getByLabelText('complexity'), { target: { value: 'high' } })
    fireEvent.change(screen.getByPlaceholderText('Send a message...'), { target: { value: 'sync me first' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    const thinkingBubble = await screen.findByText('Thinking...')
    expect(thinkingBubble).toBeInTheDocument()

    await waitFor(() => {
      expect(updateChatThreadConfig).toHaveBeenCalled()
    })
    expect(sendChatTurn).not.toHaveBeenCalled()
  })

  test('renders message bubbles without role badge headers', async () => {
    const runtime = buildRuntimePayload()
    runtime.selected_thread.messages = [
      {
        id: 101,
        role: 'assistant',
        content: 'A compact assistant reply.',
      },
    ]
    getChatRuntime.mockResolvedValueOnce(runtime)

    const { container } = renderPage()
    await screen.findByText('A compact assistant reply.')

    expect(container.querySelector('.chat-message-header')).toBeNull()
  })

  test('submits against created thread id without stale prior thread id', async () => {
    sendChatTurn.mockResolvedValue({ ok: true, thread: buildThreadPayload(2, 'Thread 2') })

    renderPage()

    await screen.findByRole('button', { name: /create thread/i })
    fireEvent.click(screen.getByRole('button', { name: /create thread/i }))

    await waitFor(() => {
      expect(createChatThread).toHaveBeenCalled()
    })

    fireEvent.change(screen.getByPlaceholderText('Send a message...'), { target: { value: 'hello new thread' } })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    await waitFor(() => {
      expect(sendChatTurn).toHaveBeenCalledWith(2, 'hello new thread')
    })
  })
})
