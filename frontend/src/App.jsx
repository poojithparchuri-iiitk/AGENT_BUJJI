import { useState, useEffect } from 'react'
import './App.css'

const API = 'http://127.0.0.1:8000'
// Sending or discarding an email needs this header, which only this page adds
const UI_HEADERS = { 'X-Bujji-UI': '1' }

function App() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [drafts, setDrafts] = useState([])
  const [busyId, setBusyId] = useState(null)
  const [notice, setNotice] = useState(null)

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
    if (!text) return

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
  }

  const sendDraft = async (draft) => {
    setBusyId(draft.id)
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
    setBusyId(null)
  }

  const discardDraft = async (draft) => {
    setBusyId(draft.id)
    setNotice(null)
    try {
      await fetch(`${API}/email/drafts/${draft.id}/discard`, {
        method: 'POST',
        headers: UI_HEADERS,
      })
      setNotice({ type: 'success', text: 'Draft discarded. Nothing was sent.' })
    } catch (err) {
      setNotice({ type: 'error', text: 'Could not discard: backend not reachable.' })
    }
    await loadDrafts()
    setBusyId(null)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') sendMessage()
  }

  return (
    <div style={{ maxWidth: '600px', margin: '40px auto', fontFamily: 'sans-serif' }}>
      <h1>Agent Bujji</h1>

      <div style={{ border: '1px solid #ccc', borderRadius: '8px', padding: '16px', minHeight: '300px', marginBottom: '16px' }}>
        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: '10px', textAlign: msg.role === 'user' ? 'right' : 'left' }}>
            <strong>{msg.role === 'user' ? 'You' : 'Bujji'}:</strong> {msg.content}
          </div>
        ))}
        {loading && <div>Bujji is typing...</div>}
      </div>

      {notice && (
        <div
          style={{
            background: notice.type === 'success' ? '#d1e7dd' : '#f8d7da',
            color: notice.type === 'success' ? '#0f5132' : '#842029',
            borderRadius: '8px',
            padding: '10px 14px',
            marginBottom: '12px',
          }}
        >
          {notice.text}
        </div>
      )}

      {drafts.map((d) => (
        <div
          key={d.id}
          style={{
            background: '#eef4ff',
            color: '#1b2a41',
            border: '1px solid #b6ccf5',
            borderRadius: '8px',
            padding: '12px 16px',
            marginBottom: '12px',
          }}
        >
          <div style={{ fontSize: '12px', fontWeight: 'bold', marginBottom: '6px' }}>
            EMAIL DRAFT (not sent yet)
          </div>
          <div><strong>To:</strong> {d.to_name ? `${d.to_name} <${d.to_email}>` : d.to_email}</div>
          <div><strong>Subject:</strong> {d.subject}</div>
          <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: '10px 0' }}>{d.body}</pre>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button onClick={() => sendDraft(d)} disabled={busyId === d.id}>
              {busyId === d.id ? 'Working...' : 'Send'}
            </button>
            <button onClick={() => discardDraft(d)} disabled={busyId === d.id}>
              Discard
            </button>
          </div>
        </div>
      ))}

      <div style={{ display: 'flex', gap: '8px' }}>
        <input
          style={{ flex: 1, padding: '8px' }}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message..."
        />
        <button onClick={sendMessage}>Send</button>
      </div>
    </div>
  )
}

export default App