// Everything about reading Bujji's replies aloud with the browser's built-in voices.

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

// Rewrites a reply so it sounds natural when read aloud
export function speechText(text) {
  return String(text)
    .replace(/\*\*/g, '')
    .replace(/`/g, '')
    .replace(/^\s*[-*]\s+/gm, '')
    .replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, (match, year, month, day) => {
      const name = MONTHS[Number(month) - 1]
      return name ? `${name} ${Number(day)}, ${year}` : match
    })
    // A time that already says AM or PM is left alone; a 24-hour time is converted
    .replace(/\b([01]?\d|2[0-3]):([0-5]\d)\b(\s*[ap]\.?m\.?)?/gi, (match, hour, minute, suffix) => {
      if (suffix) return match
      const h = Number(hour)
      const ampm = h >= 12 ? 'PM' : 'AM'
      const h12 = h % 12 === 0 ? 12 : h % 12
      return minute === '00' ? `${h12} ${ampm}` : `${h12}:${minute} ${ampm}`
    })
    .replace(/([.!?:;])\s*\n+\s*/g, '$1 ')
    .replace(/\s*\n+\s*/g, '. ')
    .replace(/\.\s*\./g, '.')
    .trim()
}

// Long utterances can stop halfway in Chrome, so read in sentence-sized pieces
export function splitForSpeech(text) {
  const sentences = text.match(/[^.!?]+[.!?]*/g) || [text]
  const chunks = []
  let current = ''
  for (const sentence of sentences) {
    if (current && (current + sentence).length > 180) {
      chunks.push(current.trim())
      current = sentence
    } else {
      current += sentence
    }
  }
  if (current.trim()) chunks.push(current.trim())
  return chunks
}

export function englishVoices() {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return []
  return window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith('en'))
}

// The chosen voice if it exists, otherwise Indian English, then British, then any English
function pickVoice(name) {
  const voices = window.speechSynthesis.getVoices()
  return (
    (name && voices.find((v) => v.name === name)) ||
    voices.find((v) => v.lang === 'en-IN') ||
    voices.find((v) => v.lang === 'en-GB') ||
    voices.find((v) => v.lang.startsWith('en')) ||
    null
  )
}

export function speak(text, voiceName = '') {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return
  const cleaned = speechText(text)
  if (!cleaned) return
  window.speechSynthesis.cancel()
  const voice = pickVoice(voiceName)
  for (const chunk of splitForSpeech(cleaned)) {
    const utterance = new SpeechSynthesisUtterance(chunk)
    if (voice) {
      utterance.voice = voice
      utterance.lang = voice.lang
    }
    window.speechSynthesis.speak(utterance)
  }
}

export function stopSpeaking() {
  if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
    window.speechSynthesis.cancel()
  }
}

function readSetting(key) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function saveSetting(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Storage may be blocked: the setting then lasts only until the page is closed
  }
}

export function readSpeakSetting() {
  return readSetting('bujji-speak') === 'on'
}

export function saveSpeakSetting(on) {
  saveSetting('bujji-speak', on ? 'on' : 'off')
}

export function readVoiceName() {
  return readSetting('bujji-voice') || ''
}

export function saveVoiceName(name) {
  saveSetting('bujji-voice', name)
}