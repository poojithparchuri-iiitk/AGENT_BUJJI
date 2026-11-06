import { useState, useEffect } from 'react'
import './App.css'

const API = 'http://127.0.0.1:8000'

function App() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [alerts, setAlerts] = useState([])

  // Every 30 seconds, ask the backend whether any reminder is due
  useEffect(() => {
    const checkReminders = async () => {
      try {
        const res = await fetch(`${API}/reminders/due`)
        const data = await res.json()
        if (data.due && data.due.length > 0) {
          setAlerts((prev) => [...prev, ...data.due])
          playBeep()
        }
      } catch (err) {
        // Backend not reachable right now: try again at the next check
      }
    }

    checkReminders()
    const timer = setInterval(checkReminders, 30000)
    return () => clearInterval(timer)
  }, [])

  const playBeep = () => {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext
      const ctx = new AudioCtx()
      const osc = ctx.createOscillator()
      osc.type = 'sine'
      osc.frequency.value = 880
      osc.connect(ctx.destination)
      osc.start()
      osc.stop(ctx.currentTime + 0.4)
    } catch (err) {
      // Some browsers block sound until the page has been clicked: ignore
    }
  }

  const dismissAlert = (index) => {
    setAlerts((prev) => prev.filter((_, i) => i !== index))
  }

  const sendMessage = async () => {
    const text = input.trim()
    if (!text) return

    // The last 6 earlier messages become Bujji's short-term memory
    const history = messages.slice(-6)

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
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

    setLoading(false)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') sendMessage()
  }

  return (
    <div style={{ maxWidth: '600px', margin: '40px auto', fontFamily: 'sans-serif' }}>
      <h1>Agent Bujji</h1>

      {alerts.map((a, i) => (
        <div
          key={`${a.id}-${i}`}
          style={{
            background: '#fff3cd',
            color: '#664d03',
            border: '1px solid #ffda6a',
            borderRadius: '8px',
            padding: '12px 16px',
            marginBottom: '10px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span>
            <strong>Reminder:</strong> {a.text} ({a.remind_at})
          </span>
          <button onClick={() => dismissAlert(i)}>Dismiss</button>
        </div>
      ))}

      <div style={{ border: '1px solid #ccc', borderRadius: '8px', padding: '16px', minHeight: '300px', marginBottom: '16px' }}>
        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: '10px', textAlign: msg.role === 'user' ? 'right' : 'left' }}>
            <strong>{msg.role === 'user' ? 'You' : 'Bujji'}:</strong> {msg.content}
          </div>
        ))}
        {loading && <div>Bujji is typing...</div>}
      </div>
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