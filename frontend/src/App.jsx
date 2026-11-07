import { useState, useEffect, useRef } from 'react'
import './App.css'

const API = 'http://127.0.0.1:8000'
// Sending or discarding an email needs this header, which only this page adds
const UI_HEADERS = { 'X-Bujji-UI': '1' }

// Example requests shown on the empty screen. Clicking one fills the box; it does not send.
const STARTERS = [
  'Remind me to stretch in 10 minutes',
  "What's on my schedule tomorrow?",
  'Add a task: submit the report',
  'I finished my SQL assignment',
]

// Turns **bold** in a reply into real bold text. React escapes everything else.
function renderText(text) {
  return String(text)
    .split(/(\*\*[^*]+\*\*)/g)
    .map((part, i) =>
      part.length > 4 && part.startsWith('**') && part.endsWith('**') ? (
        <strong key={i}>{part.slice(2, -2)}</strong>
      ) : (
        part
      )
    )
}

// Bujji's face. state is "idle" or "thinking"; later, voice mode can reuse these states.
function BujjiMark({ state }) {
  return (
    <svg
      className="mark"
      data-state={state}
      viewBox="0 0 48 48"
      role="img"
      aria-label={state === 'thinking' ? 'Bujji is thinking' : 'Bujji'}
    >
      <rect className="mark-body" x="4" y="6" width="40" height="36" rx="16" />
      <g className="mark-eyes">
        <ellipse className="mark-eye" cx="18" cy="23" rx="3.2" ry="4.2" />
        <ellipse className="mark-eye" cx="30" cy="23" rx="3.2" ry="4.2" />
      </g>
      <path className="mark-mouth" d="M19 32 Q24 36 29 32" />
    </svg>
  )
}

function App() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [drafts, setDrafts] = useState([])
  const [busy, setBusy] = useState(null) // { id, action } while a draft is being sent or discarded
  const [notice, setNotice] = useState(null)

  const endRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    document.title = 'Agent Bujji'
  }, [])

  // Keep the newest message in view
  useEffect(() => {
    const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    endRef.current?.scrollIntoView({ behavior: calm ? 'auto' : 'smooth', block: 'end' })
  }, [messages, loading, drafts.length])

  const loadDrafts = async () => {
    try {
      const res = await fetch(`${API}/email/drafts`)
      const data = await res.json()
      setDrafts(data.drafts || [])
    } catch (err) {
      // Backend not reachable right now: keep what is on screen
    }
  }

  // Show drafts that are already waiting when the page opens
  useEffect(() => {
    loadDrafts()
  }, [])

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || loading) return

    // The last 6 earlier messages become Bujji's short-term memory
    const history = messages.slice(-6)

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setNotice(null)
    setLoading(true)

    try {
      const res = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history: history }),
      })
      const data = await res.json()
      setMessages((prev) => [...prev, { role: 'assistant', content: data.reply }])
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Error connecting to backend' }])
    }

    await loadDrafts()
    setLoading(false)
    inputRef.current?.focus()
  }

  const sendDraft = async (draft) => {
    setBusy({ id: draft.id, action: 'send' })
    setNotice(null)
    try {
      const res = await fetch(`${API}/email/drafts/${draft.id}/send`, {
        method: 'POST',
        headers: UI_HEADERS,
      })
      const data = await res.json()
      if (data.ok) {
        setNotice({ type: 'success', text: `Email sent to ${draft.to_email}.` })
      } else {
        setNotice({ type: 'error', text: `Not sent: ${data.error || data.detail || 'unknown error'}` })
      }
    } catch (err) {
      setNotice({ type: 'error', text: 'Not sent: could not reach the backend.' })
    }
    await loadDrafts()
    setBusy(null)
  }

  const discardDraft = async (draft) => {
    setBusy({ id: draft.id, action: 'discard' })
    setNotice(null)
    try {
      await fetch(`${API}/email/drafts/${draft.id}/discard`, {
        method: 'POST',
        headers: UI_HEADERS,
      })
      setNotice({ type: 'success', text: 'Draft discarded. Nothing was sent.' })
    } catch (err) {
      setNotice({ type: 'error', text: 'Could not discard the draft: backend not reachable.' })
    }
    await loadDrafts()
    setBusy(null)
  }

  const pickStarter = (text) => {
    setInput(text)
    inputRef.current?.focus()
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="app">
      <header className="top">
        <BujjiMark state={loading ? 'thinking' : 'idle'} />
        <h1 className="wordmark">Bujji</h1>
      </header>

      <main className="chat" role="log" aria-label="Conversation">
        {messages.length === 0 && !loading && (
          <section className="empty">
            <p className="empty-hello">Hi, I'm Bujji. What are we doing today?</p>
            <div className="starters">
              {STARTERS.map((s) => (
                <button key={s} className="starter" onClick={() => pickStarter(s)}>
                  {s}
                </button>
              ))}
            </div>
          </section>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`msg ${msg.role === 'user' ? 'msg-user' : 'msg-bujji'}`}>
            <p>{renderText(msg.content)}</p>
          </div>
        ))}

        {loading && (
          <div className="msg msg-bujji" role="status" aria-label="Bujji is thinking">
            <span className="dots">
              <i />
              <i />
              <i />
            </span>
          </div>
        )}

        <div ref={endRef} />
      </main>

      <footer className="dock">
        {notice && (
          <div
            className={`notice notice-${notice.type}`}
            role={notice.type === 'error' ? 'alert' : 'status'}
          >
            {notice.text}
          </div>
        )}

        {drafts.length > 0 && (
          <div className="drafts">
            {drafts.map((d) => (
              <article className="draft" key={d.id}>
                <span className="chip">Not sent yet</span>
                <dl className="draft-meta">
                  <dt>To</dt>
                  <dd>{d.to_name ? `${d.to_name} <${d.to_email}>` : d.to_email}</dd>
                  <dt>Subject</dt>
                  <dd>{d.subject}</dd>
                </dl>
                <div className="draft-body">
                  <p className="draft-text">{d.body}</p>
                </div>
                <div className="draft-actions">
                  <button
                    className="btn btn-primary"
                    onClick={() => sendDraft(d)}
                    disabled={busy?.id === d.id}
                  >
                    {busy?.id === d.id && busy.action === 'send' ? 'Sending…' : 'Send email'}
                  </button>
                  <button
                    className="btn btn-quiet"
                    onClick={() => discardDraft(d)}
                    disabled={busy?.id === d.id}
                  >
                    {busy?.id === d.id && busy.action === 'discard' ? 'Discarding…' : 'Discard draft'}
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}

        <div className="composer">
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message Bujji"
            aria-label="Message Bujji"
            autoFocus
          />
          <button
            className="send"
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            aria-label="Send message"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </footer>
    </div>
  )
}

export default App