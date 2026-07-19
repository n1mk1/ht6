import { useEffect, useRef, useState } from 'react'
import { askAssistant } from './assistantApi'
import type { UIContext } from './contextBuilder'
import './AssistantPanel.css'

const STARTER_QUESTIONS = [
  'What does this page show?',
  'What does Stability mean?',
  'Where do I find the latest session?',
  'What should I click to compare two sessions?',
]

const MAX_QUESTION_CHARS = 500

type Message = { role: 'user' | 'assistant'; text: string }

/** Accessible help panel for the RehabTrace dashboard. */
export default function AssistantPanel({ uiContext }: { uiContext: UIContext }) {
  const [open, setOpen] = useState(false)
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [mockMode, setMockMode] = useState(false)

  const inputRef = useRef<HTMLInputElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const messagesRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [messages, loading])

  useEffect(() => {
    if (!open) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setOpen(false)
        return
      }
      // Keep Tab focus inside the dialog while it is open.
      if (e.key === 'Tab' && panelRef.current) {
        const focusable = panelRef.current.querySelectorAll<HTMLElement>(
          'button, input, [tabindex]:not([tabindex="-1"])',
        )
        if (focusable.length === 0) return
        const first = focusable[0]
        const last = focusable[focusable.length - 1]
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  async function submit(text: string) {
    const q = text.trim()
    if (!q || loading) return
    setError('')
    setQuestion('')
    setMessages((prev) => [...prev, { role: 'user', text: q }])
    setLoading(true)
    try {
      const res = await askAssistant(q, uiContext)
      setMockMode(Boolean(res.mock))
      setMessages((prev) => [...prev, { role: 'assistant', text: res.answer }])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Something went wrong.')
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        className="assistant-launcher"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
      >
        <span aria-hidden="true">?</span> Help me understand this screen
      </button>
    )
  }

  return (
    <div
      className="assistant-panel"
      role="dialog"
      aria-modal="false"
      aria-label="Screen help assistant"
      ref={panelRef}
    >
      <div className="assistant-header">
        <h2 id="assistant-title">Screen Help</h2>
        <button
          type="button"
          className="assistant-close"
          onClick={() => setOpen(false)}
          aria-label="Close help panel"
        >
          Close ✕
        </button>
      </div>

      <p className="assistant-intro">
        Ask me about anything you see on this screen. I explain what things mean and where to
        find them. For questions about your health or progress, please speak with your
        therapist.
      </p>

      {mockMode && (
        <p className="assistant-mock-note">
          Practice mode: answers are examples, not generated live.
        </p>
      )}

      <div className="assistant-messages" ref={messagesRef} aria-live="polite">
        {messages.length === 0 && (
          <div className="assistant-starters">
            <p id="assistant-starters-label">You could start with one of these:</p>
            <ul aria-labelledby="assistant-starters-label">
              {STARTER_QUESTIONS.map((s) => (
                <li key={s}>
                  <button type="button" className="assistant-starter" onClick={() => void submit(s)}>
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`assistant-msg assistant-msg-${msg.role}`}>
            <span className="assistant-msg-who">{msg.role === 'user' ? 'You' : 'Guide'}</span>
            <p>{msg.text}</p>
          </div>
        ))}
        {loading && (
          <p className="assistant-loading" role="status">
            Finding the answer…
          </p>
        )}
        {error && (
          <p className="assistant-error" role="alert">
            {error}
          </p>
        )}
      </div>

      <form
        className="assistant-input-row"
        onSubmit={(e) => {
          e.preventDefault()
          void submit(question)
        }}
      >
        <label htmlFor="assistant-question" className="assistant-input-label">
          Type your question
        </label>
        <div className="assistant-input-controls">
          <input
            id="assistant-question"
            ref={inputRef}
            type="text"
            value={question}
            maxLength={MAX_QUESTION_CHARS}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="For example: What does Accuracy mean?"
            disabled={loading}
          />
          <button type="submit" disabled={loading || !question.trim()}>
            Ask
          </button>
        </div>
      </form>
    </div>
  )
}
