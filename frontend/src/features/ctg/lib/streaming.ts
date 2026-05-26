"use client"

import {AXIOS_INSTANCE} from "@/shared/lib/axios-custom-instance"
import {nanoid} from "nanoid";

export type MomentPoint = {
    monitor_id: string
    time_s: number
    real_time?: string
    fhr_bpm: number
    uterus_data: number
    stop?: 0 | 1
}

export type MomentsBatchMsg = {
    kind: "moments_batch"
    monitor_id: string
    t_start: number
    t_end: number
    moments: MomentPoint[]
    warnings?: string[]
}

export type Interval = { start: number; end: number; color_id: number }

export type AnnotationIntervals = {
    kind: "annotation"
    monitor_id: string
    t_start: number
    t_end: number
    time_s?: number[]
    fhr_line_status?: number[] | Interval[]
    fhr_event_status?: number[] | Interval[]
    toco_line_status?: number[] | Interval[]
    toco_tachysystole?: number[] | Interval[]
    toco_hypertonus?: number[] | Interval[]
    toco_tetanic?: number[] | Interval[]
    warnings?: string[]
}

export type SessionCompleteMsg = { kind: "session_complete"; monitor_id: string; message?: string }

export type StreamMessage = MomentsBatchMsg | AnnotationIntervals | SessionCompleteMsg

// Цвета как в клиентском эмуляторе Python
export const FHR_LINE_COLORS: Record<number, string> = {
    [-2]: "#8B0000", // тяжёлая брадикардия (<100)
    [-1]: "#FF4444", // брадикардия (<120)
    [0]: "#2ECC71",  // норма (120-160)
    [1]: "#FF8C00",  // тахикардия (>160)
  [2]: "#627EA7",  // тяжёлая тахикардия (>180) (как в эмуляторе)
}

export const FHR_BACKGROUND_COLORS: Record<number, string> = {
    [-1]: "#ADD8E6", // децелерация (голубой)
    [0]: '',        // норма
    [1]: "#DDA0DD", // акселерация (светло-фиолетовый)
}

export const TOCO_LINE_COLORS: Record<number, string> = {
    [0]: "#2ECC71", // низкая интенсивность (зелёный)
    [1]: "#FFA500", // средняя интенсивность (оранжевый)
    [2]: "#FF4444", // высокая интенсивность (красный)
}

export const TOCO_BACKGROUND_COLORS: Record<string, string> = {
    tachysystole: "#FFE4B5",
    hypertonus: "#FFB6C1",
    tetanic: "#427152",
}

export type StartRealtimeParams = {
    monitor_id?: string | null
    interval_sec?: number
    fs?: number
    speed?: number
}

export type StartInstantParams = {
    monitor_id?: string | null
    interval_sec?: number
    fs?: number
    speed?: number
}

export type StartUploadResponse = { monitor_id: string }

// Типы ответа для /api/instant
export type InstantMoment = { time_s: number; real_time?: string; fhr_bpm: number; uterus_data: number }
export type InstantAnnotation = {
    fhr_line_status?: Interval[] | number[]
    fhr_event_status?: Interval[] | number[]
    toco_line_status?: Interval[] | number[]
    toco_tachysystole?: Interval[] | number[]
    toco_hypertonus?: Interval[] | number[]
    toco_tetanic?: Interval[] | number[]
    warnings?: string[]
}
export type InstantResponse = {
    monitor_id: string
    duration_sec?: number
    moments: InstantMoment[]
    annotations: InstantAnnotation | InstantAnnotation[]
}

export async function getInstantByMonitorId(monitor_id: string): Promise<InstantResponse> {
  const search = new URLSearchParams()
  search.set("monitor_id", monitor_id)
  const { data } = await AXIOS_INSTANCE.get(`/api/instant?${search.toString()}`)
  return data as InstantResponse
}

export async function startRealtime(
    fhr_file: Blob,
    uterus_file: Blob,
    params: StartRealtimeParams
): Promise<StartUploadResponse> {
    const form = new FormData()
    form.append("fhr_file", fhr_file)
    form.append("uterus_file", uterus_file)

    const search = new URLSearchParams()
    if (params.monitor_id) search.set("monitor_id", String(params.monitor_id))
    if (params.interval_sec != null) search.set("interval_sec", String(params.interval_sec))
    if (params.fs != null) search.set("fs", String(params.fs))
    if (params.speed != null) search.set("speed", String(params.speed))

    const {data} = await AXIOS_INSTANCE.post(`/api/upload?${search.toString()}`, form, {
        headers: {"Content-Type": "multipart/form-data"},
    })
    // ожидаем { monitor_id }
    return (data as StartUploadResponse) ?? {monitor_id: params.monitor_id ?? nanoid()}
}

export async function runInstant(
    fhr_file: Blob,
    uterus_file: Blob,
    params: StartInstantParams
): Promise<InstantResponse> {
    const form = new FormData()
    form.append("fhr_file", fhr_file)
    form.append("uterus_file", uterus_file)
    const search = new URLSearchParams()
    if (params.monitor_id) search.set("monitor_id", String(params.monitor_id))
    if (params.interval_sec != null) search.set("interval_sec", String(params.interval_sec))
    if (params.fs != null) search.set("fs", String(params.fs))
    if (params.speed != null) search.set("speed", String(params.speed))
    const {data} = await AXIOS_INSTANCE.post(`/api/instant?${search.toString()}`, form, {
        headers: {"Content-Type": "multipart/form-data"},
    })
    return data as InstantResponse
}

export function parseStreamedJson(text: string): StreamMessage[] {
    const result: StreamMessage[] = []
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
                const obj = JSON.parse(buf.trim()) as StreamMessage
                result.push(obj)
                buf = ""
            } catch {
                // попробуем по переносам строк
                const lines = buf.split(/\n+/).filter(Boolean)
                for (const line of lines) {
                    try {
                        const obj = JSON.parse(line) as StreamMessage
                        result.push(obj)
                    } catch {
                        // игнорируем, возможно неполный chunk
                    }
                }
                buf = ""
            }
        }
    }
    return result
}

// Разбор SSE чанков вида "data: {...}\n\n" с поддержкой нескольких data: в одном событии
function parseSSEChunk(chunk: string): { messages: StreamMessage[]; rest: string } {
    const messages: StreamMessage[] = []
    const parts = chunk.split(/\n\n/)
    const rest = parts.pop() ?? ""
    for (const ev of parts) {
        const dataLines = ev.split(/\n/).filter(l => /^data:\s*/.test(l))
        for (const line of dataLines) {
            const jsonStr = line.replace(/^data:\s*/, "").trim()
            try {
                messages.push(JSON.parse(jsonStr) as StreamMessage)
            } catch {
                messages.push(...parseStreamedJson(jsonStr))
            }
        }
    }
    return { messages, rest }
}

export type StreamConnection = { abort: () => void }
export type StreamOptions = { throttleMs?: number }

export async function connectStream(
    monitorId: string,
    onMessage: (msg: StreamMessage) => void,
    onError?: (e: unknown) => void,
    opts?: StreamOptions
): Promise<StreamConnection> {
  // если есть поддержка Worker, используем пул воркера для неблокирующей обработки
  try {
    if (typeof window !== 'undefined' && 'Worker' in window) {
      const worker = new Worker(new URL('./stream-worker.ts', import.meta.url), { type: 'module' })
      const base = AXIOS_INSTANCE.defaults.baseURL ?? ""
      const handle = (ev: MessageEvent<any>) => {
        const data = ev.data
        if (!data || typeof data !== 'object') return
        if (data.type === 'message' && data.monitorId === monitorId) {
          onMessage(data.payload as StreamMessage)
        } else if (data.type === 'error' && data.monitorId === monitorId) {
          onError?.(data.error)
        }
      }
      worker.addEventListener('message', handle)
      worker.postMessage({ type: 'subscribe', monitorId, baseUrl: base, throttleMs: opts?.throttleMs ?? 120 })
      return {
        abort: () => {
          try { worker.postMessage({ type: 'unsubscribe', monitorId }) } catch {}
          worker.removeEventListener('message', handle)
          try { worker.terminate() } catch {}
        }
      }
    }
  } catch {}
    const controller = new AbortController()
    const base = AXIOS_INSTANCE.defaults.baseURL ?? ""
    const url = `${base ? base.replace(/\/$/, "") : ""}/api/stream/${monitorId}`

    try {
        const res = await fetch(url, {method: "GET", signal: controller.signal})
        if (!res.body) throw new Error("Нет body у стрима")
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let carry = ""
        let queue: StreamMessage[] = []
        let timer: any = null
        const MAX_CARRY = 1_000_000
        const MAX_QUEUE = 1000
        const raf = (cb: () => void) => (typeof window !== 'undefined' && 'requestAnimationFrame' in window ? window.requestAnimationFrame(cb) : setTimeout(cb, Math.max(0, opts?.throttleMs ?? 100)))
        const flush = () => {
            const batch = queue
            queue = []
            for (const m of batch) onMessage(m)
        }
        const schedule = () => {
            if (timer != null) return
            const delay = Math.max(0, opts?.throttleMs ?? 100)
            timer = setTimeout(() => {
                timer = null
                raf(() => flush())
            }, delay)
        }
        (async () => {
            try {
                while (true) {
                    const {done, value} = await reader.read()
                    if (done) break
                    const chunk = decoder.decode(value, {stream: true})
                    // Сначала пытаемся распарсить как SSE
                    const sse = parseSSEChunk(carry + chunk)
                    if (sse.messages.length > 0) {
                        carry = sse.rest
                        queue.push(...sse.messages)
                        if (queue.length >= MAX_QUEUE) flush()
                        else schedule()
                        continue
                    }
                    // Fallback: обычный json-стрим
                    const messages = parseStreamedJson(carry + chunk)
                    if (messages.length === 0) {
                        carry += chunk
                        if (carry.length > MAX_CARRY) carry = carry.slice(-MAX_CARRY)
                    } else {
                        carry = ""
                        queue.push(...messages)
                        if (queue.length >= MAX_QUEUE) flush()
                        else schedule()
                    }
                }
            } catch (e) {
                onError?.(e)
            }
        })()
    } catch (e) {
        onError?.(e)
    }

    return {abort: () => controller.abort()}
}

export function arrayToIntervals(values: number[] | undefined, tStart = 0, step = 1): Interval[] {
    if (!values || values.length === 0) return []
    const res: Interval[] = []
    let curr = values[0]
    let start = tStart
    for (let i = 1; i < values.length; i++) {
        if (values[i] !== curr) {
            res.push({start, end: tStart + i * step, color_id: curr})
            start = tStart + i * step
            curr = values[i]
        }
    }
    res.push({start, end: tStart + values.length * step, color_id: curr})
    return res
}

export function ensureIntervals(field?: number[] | Interval[], tStart = 0, step = 1): Interval[] {
    if (!field) return []
    if (Array.isArray(field) && typeof field[0] === "number") {
        return arrayToIntervals(field as number[], tStart, step)
    }
    return field as Interval[]
}

export type LivePoint = { index: number; heart_beat: number; pussy_power: number; rt?: string; ts?: number }

/**
 * Слияние по времени: вычисляет индекс из time_s и заменяет существующие точки
 * если пришли уточнённые значения за прошлое время. Поддерживает паузы и возобновление.
 */
export function mergeMomentsByTime(
    target: LivePoint[],
    batch: MomentsBatchMsg,
    originSecRef: { current: number | null },
    sampleMs: number
): LivePoint[] {
    const stepSec = sampleMs / 1000
    if (originSecRef.current == null) {
        originSecRef.current = Math.min(batch.t_start ?? 0, batch.moments[0]?.time_s ?? 0)
    }
    const origin = originSecRef.current
    const out: LivePoint[] = [...target]
    for (const m of batch.moments) {
        const idx = Math.max(0, Math.round((m.time_s - origin) / stepSec))
        if (idx >= out.length) {
            // расширяем массив пустыми промежутками, если пришёл пропуск
            for (let i = out.length; i < idx; i++) {
                const prev = out[i - 1] ?? {heart_beat: 0, pussy_power: 0, rt: undefined, ts: i * stepSec}
                out[i] = {index: i, heart_beat: prev.heart_beat, pussy_power: prev.pussy_power, rt: prev.rt, ts: i * stepSec}
            }
            out[idx] = {index: idx, heart_beat: m.fhr_bpm, pussy_power: m.uterus_data, rt: m.real_time, ts: m.time_s - origin}
        } else {
            // замена прошлых значений (уточнение)
            out[idx] = {index: idx, heart_beat: m.fhr_bpm, pussy_power: m.uterus_data, rt: m.real_time, ts: m.time_s - origin}
        }
    }
    // Не ограничиваем длину истории, чтобы полностью отображать данные от эмулятора
    return out
}


