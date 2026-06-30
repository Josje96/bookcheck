// Typed client for the bookcheck FastAPI backend. In dev these relative URLs
// are proxied to http://localhost:8000 by Vite (see vite.config.ts).

export interface Health {
  ok: boolean
  ollama: boolean
  models: string[]
  has_manuscript: boolean
  has_source: boolean
  chat_provider: string
  gemini_configured: boolean
  deepseek_configured: boolean
  last_provider: string | null
  last_model: string | null
  username: string
}

export type Provider = "ollama" | "gemini" | "deepseek"

export interface Trait {
  attribute: string
  value: string
}

export interface Character {
  name: string
  aliases: string[]
  species: string | null
  role: string | null
  description: string | null
  strengths: string | null
  weaknesses: string | null
  arc: string | null
  development: string | null
  traits: Trait[]
}

export interface LocationInfo {
  name: string
  description: string | null
}

export interface Relationship {
  a: string
  b: string
  relation: string
}

export interface Chapter {
  chapter_seq: number
  pov_character: string | null
  date_label: string | null
  summary: string | null
  uncertainties: string[]
}

export interface Contradiction {
  description: string
  severity: string | null
  source_a: { quote: string; ref: string }
  source_b: { quote: string; ref: string }
}

export interface TimelineEvent {
  when: string | null
  event: string
  ref: string
}

export interface Bible {
  meta: { chapters: number; characters: number }
  impression: string | null
  chapters: Chapter[]
  characters: Character[]
  contradictions: Contradiction[]
  locations: LocationInfo[]
  relationships: Relationship[]
  timeline: TimelineEvent[]
}

export interface RunStep {
  key: string
  label: string
}

export interface RunStatus {
  id?: string
  status: string // queued | running | done | error | none
  step?: string | null
  step_index?: number
  total_steps?: number
  message?: string
  error?: string | null
  elapsed_s?: number
  provider?: string
  model?: string | null
  finished_at?: number | null
  steps?: RunStep[]
}

export interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

async function asJson<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error((await r.text()) || r.statusText)
  return r.json() as Promise<T>
}

export const api = {
  health: () => fetch("/api/health").then(asJson<Health>),

  bible: () => fetch("/api/bible").then(asJson<Bible>),

  report: () =>
    fetch("/api/report").then((r) => {
      if (!r.ok) throw new Error("No report yet.")
      return r.text()
    }),

  latestRun: () => fetch("/api/runs").then(asJson<RunStatus>),

  run: (id: string) => fetch(`/api/runs/${id}`).then(asJson<RunStatus>),

  startRun: (form: FormData) =>
    fetch("/api/runs", { method: "POST", body: form }).then(asJson<RunStatus>),
}

/**
 * Stream a chat reply. The backend sends Server-Sent Events with two channels:
 * "thinking" (live reasoning) and "answer" (the clean reply). Calls the
 * matching handler for each chunk; resolves when the stream ends.
 */
export async function streamChat(
  messages: ChatMessage[],
  handlers: {
    onThinking?: (chunk: string) => void
    onAnswer?: (chunk: string) => void
    onError?: (msg: string) => void
  },
  provider?: Provider,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages, provider }),
    signal,
  })
  if (!res.ok) {
    handlers.onError?.((await res.text()) || res.statusText)
    return
  }
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ""
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const blocks = buf.split("\n\n")
    buf = blocks.pop() ?? ""
    for (const block of blocks) {
      let event = "message"
      let data = ""
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim()
        else if (line.startsWith("data: ")) data = line.slice(6)
      }
      if (!data) continue
      let text: string
      try {
        text = JSON.parse(data)
      } catch {
        continue
      }
      if (event === "thinking") handlers.onThinking?.(text)
      else if (event === "answer") handlers.onAnswer?.(text)
      else if (event === "error") handlers.onError?.(text)
    }
  }
}
