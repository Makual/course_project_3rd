/*
  Web Worker: пул стрим-коннекшенов SSE/Fetch для неблокирующего UI
*/

// Сообщения из main-thread
type SubscribeMsg = { type: 'subscribe'; monitorId: string; baseUrl?: string | null; throttleMs?: number }
type UnsubscribeMsg = { type: 'unsubscribe'; monitorId: string }
type ShutdownMsg = { type: 'shutdown' }
type InMsg = SubscribeMsg | UnsubscribeMsg | ShutdownMsg

// Сообщения в main-thread
type OutMsg =
  | { type: 'message'; monitorId: string; payload: any }
  | { type: 'error'; monitorId: string; error: string }
  | { type: 'closed'; monitorId: string }

type Conn = {
  controller: AbortController
  queue: any[]
  timer: any
  carry: string
  flush: () => void
}

const conns = new Map<string, Conn>()

function post(m: OutMsg) {
  // @ts-ignore
  postMessage(m)
}

function parseStreamedJson(text: string): any[] {
  const result: any[] = []
  let buf = ""
  let depth = 0
  let inStr = false
  for (const ch of text) {
    buf += ch
    if (ch === '"' && buf[buf.length - 2] !== "\\") inStr = !inStr
    if (inStr) continue
    if (ch === "{") depth += 1
    if (ch === "}") depth -= 1
    if (depth === 0 && buf.trim()) {
      try {
        const obj = JSON.parse(buf.trim())
        result.push(obj)
        buf = ""
      } catch {
        const lines = buf.split(/\n+/).filter(Boolean)
        for (const line of lines) {
          try {
            const obj = JSON.parse(line)
            result.push(obj)
          } catch {}
        }
        buf = ""
      }
    }
  }
  return result
}

function parseSSEChunk(chunk: string): { messages: any[]; rest: string } {
  const messages: any[] = []
  const parts = chunk.split(/\n\n/)
  const rest = parts.pop() ?? ""
  for (const ev of parts) {
    const dataLines = ev.split(/\n/).filter(l => /^data:\s*/.test(l))
    for (const line of dataLines) {
      const jsonStr = line.replace(/^data:\s*/, "").trim()
      try {
        messages.push(JSON.parse(jsonStr))
      } catch {
        messages.push(...parseStreamedJson(jsonStr))
      }
    }
  }
  return { messages, rest }
}

async function openStream(monitorId: string, baseUrl?: string | null, throttleMs = 120) {
  const url = `${baseUrl ? baseUrl.replace(/\/$/, '') : ''}/api/stream/${encodeURIComponent(monitorId)}`
  const controller = new AbortController()
  const conn: Conn = { controller, queue: [], timer: null, carry: "", flush() {
    const batch = this.queue
    this.queue = []
    for (const msg of batch) post({ type: 'message', monitorId, payload: msg })
  }}
  conns.set(monitorId, conn)
  try {
    const res = await fetch(url, { method: 'GET', signal: controller.signal })
    if (!res.body) throw new Error('Нет body у стрима')
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    const MAX_CARRY = 1_000_000
    const MAX_QUEUE = 1000
    const schedule = () => {
      if (conn.timer != null) return
      const delay = Math.max(0, throttleMs)
      conn.timer = setTimeout(() => { conn.timer = null; conn.flush() }, delay)
    }
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value, { stream: true })
      const sse = parseSSEChunk(conn.carry + chunk)
      if (sse.messages.length > 0) {
        conn.carry = sse.rest
        conn.queue.push(...sse.messages)
        if (conn.queue.length >= MAX_QUEUE) conn.flush(); else schedule()
        continue
      }
      const messages = parseStreamedJson(conn.carry + chunk)
      if (messages.length === 0) {
        conn.carry += chunk
        if (conn.carry.length > MAX_CARRY) conn.carry = conn.carry.slice(-MAX_CARRY)
      } else {
        conn.carry = ""
        conn.queue.push(...messages)
        if (conn.queue.length >= MAX_QUEUE) conn.flush(); else schedule()
      }
    }
    post({ type: 'closed', monitorId })
  } catch (e: any) {
    post({ type: 'error', monitorId, error: String(e?.message ?? e) })
  }
}

// @ts-ignore
self.onmessage = (ev: MessageEvent<InMsg>) => {
  const msg = ev.data
  if (msg.type === 'subscribe') {
    if (conns.has(msg.monitorId)) return
    openStream(msg.monitorId, msg.baseUrl, msg.throttleMs)
  } else if (msg.type === 'unsubscribe') {
    const c = conns.get(msg.monitorId)
    if (c) {
      try { c.controller.abort() } catch {}
      clearTimeout(c.timer)
      conns.delete(msg.monitorId)
    }
  } else if (msg.type === 'shutdown') {
    for (const [id, c] of conns) {
      try { c.controller.abort() } catch {}
      clearTimeout(c.timer)
      conns.delete(id)
    }
  }
}






