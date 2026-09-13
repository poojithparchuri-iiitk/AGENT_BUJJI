import { useState, useEffect } from 'react'
import './App.css'

function App() {
  const [message, setMessage] = useState('Loading...')

  useEffect(() => {
    fetch('http://127.0.0.1:8000/')
      .then((res) => res.json())
      .then((data) => setMessage(data.message))
      .catch((err) => setMessage('Error connecting to backend'))
  }, [])

  return (
    <div>
      <h1>Agent Bujji</h1>
      <p>{message}</p>
    </div>
  )
}

export default App