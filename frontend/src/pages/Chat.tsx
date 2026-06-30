import { useEffect, useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { SendHorizonal, Loader2, ChevronDown, Brain, Cpu, Cloud, Zap, SquarePen } from "lucide-react"
import { streamChat, type ChatMessage, type Provider } from "@/lib/api"
import { useBookcheck } from "@/lib/store"
import { Button } from "@/components/ui/button"
import { EmptyManuscript, Loading } from "@/components/PageState"
import { cn } from "@/lib/utils"

interface Turn {
  role: "user" | "assistant"
  content: string
  thinking?: string
}

const STORAGE_KEY = "bookcheck:chat"

function loadTurns(): Turn[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveTurns(turns: Turn[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(turns))
  } catch { /* quota exceeded, ignore */ }
}

export default function Chat() {
  const { health, loading } = useBookcheck()
  const [turns, setTurns] = useState<Turn[]>(loadTurns)
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const [provider, setProvider] = useState<Provider>("ollama")
  const bottomRef = useRef<HTMLDivElement>(null)

  // Persist turns on every change.
  useEffect(() => { saveTurns(turns) }, [turns])

  // Default provider: last analysis run's provider, then server default.
  useEffect(() => {
    const lp = health?.last_provider
    if (lp === "gemini" || lp === "ollama" || lp === "deepseek") {
      setProvider(lp as Provider)
    } else {
      const p = health?.chat_provider
      if (p === "gemini" || p === "ollama" || p === "deepseek") setProvider(p as Provider)
    }
  }, [health?.last_provider, health?.chat_provider])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [turns])

  if (loading) return <Loading />
  if (!health?.has_manuscript) return <EmptyManuscript />

  function newChat() {
    if (busy) return
    setTurns([])
    setInput("")
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch { /* ignore */ }
  }

  async function send() {
    const text = input.trim()
    if (!text || busy) return
    setInput("")
    setBusy(true)

    const history = [...turns, { role: "user", content: text } as Turn]
    setTurns([...history, { role: "assistant", content: "", thinking: "" }])

    const payload: ChatMessage[] = history.map((t) => ({
      role: t.role,
      content: t.content,
    }))

    const updateLast = (fn: (t: Turn) => Turn) =>
      setTurns((prev) => {
        const copy = [...prev]
        copy[copy.length - 1] = fn(copy[copy.length - 1])
        return copy
      })

    try {
      await streamChat(
        payload,
        {
          onThinking: (c) =>
            updateLast((t) => ({ ...t, thinking: (t.thinking ?? "") + c })),
          onAnswer: (c) => updateLast((t) => ({ ...t, content: t.content + c })),
          onError: (m) =>
            updateLast((t) => ({
              ...t,
              content: t.content + `\n\n_Error: ${m}_`,
            })),
        },
        provider,
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between border-b px-8 py-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Chat</h1>
          <p className="text-sm text-muted-foreground">
            Ask about your manuscript - answers are grounded in the story bible.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {turns.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={newChat}
              disabled={busy}
              title="Clear this conversation and start fresh"
            >
              <SquarePen className="size-3.5" />
              New chat
            </Button>
          )}
          <ProviderToggle
            value={provider}
            onChange={setProvider}
            disabled={busy}
            geminiReady={!!health.gemini_configured}
            deepseekReady={!!health.deepseek_configured}
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto max-w-3xl space-y-5">
          {turns.length === 0 && <Suggestions onPick={setInput} />}
          {turns.map((t, i) => (
            <Bubble key={i} turn={t} streaming={busy && i === turns.length - 1} />
          ))}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="border-t px-8 py-4">
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
            placeholder="Ask about a character, a plot thread, the pacing…"
            rows={1}
            className="max-h-40 min-h-[2.5rem] flex-1 resize-none rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <Button onClick={() => void send()} disabled={busy || !input.trim()} size="icon">
            {busy ? <Loader2 className="animate-spin" /> : <SendHorizonal />}
          </Button>
        </div>
        <p className="mx-auto mt-2 max-w-3xl text-center text-xs text-muted-foreground">
          Replies are slow on a local GPU - the model thinks before answering.
        </p>
      </div>
    </div>
  )
}

function Bubble({ turn, streaming }: { turn: Turn; streaming: boolean }) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
          {turn.content}
        </div>
      </div>
    )
  }
  const waiting = streaming && !turn.content
  return (
    <div className="space-y-2">
      {turn.thinking && <Thinking text={turn.thinking} open={waiting} />}
      <div className="max-w-[80%] rounded-2xl rounded-bl-sm bg-muted px-4 py-2.5 text-sm">
        {turn.content ? (
          <div className="markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {turn.content}
            </ReactMarkdown>
          </div>
        ) : (
          <span className="inline-flex items-center gap-2 text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" /> thinking…
          </span>
        )}
      </div>
    </div>
  )
}

function Thinking({ text, open }: { text: string; open: boolean }) {
  const [show, setShow] = useState(open)
  useEffect(() => {
    setShow(open)
  }, [open])
  return (
    <div className="max-w-[80%] rounded-lg border bg-card text-xs text-muted-foreground">
      <button
        onClick={() => setShow((s) => !s)}
        className="flex w-full items-center gap-1.5 px-3 py-2 font-medium"
      >
        <Brain className="size-3.5" />
        Reasoning
        <ChevronDown
          className={cn("ml-auto size-3.5 transition-transform", show && "rotate-180")}
        />
      </button>
      {show && (
        <div className="whitespace-pre-wrap border-t px-3 py-2 leading-relaxed">
          {text}
        </div>
      )}
    </div>
  )
}

function ProviderToggle({
  value,
  onChange,
  disabled,
  geminiReady,
  deepseekReady,
}: {
  value: Provider
  onChange: (p: Provider) => void
  disabled: boolean
  geminiReady: boolean
  deepseekReady: boolean
}) {
  const opts: {
    id: Provider
    label: string
    icon: typeof Cpu
    ready: boolean
    hint?: string
  }[] = [
    { id: "ollama", label: "Local", icon: Cpu, ready: true },
    {
      id: "gemini",
      label: "Gemini",
      icon: Cloud,
      ready: geminiReady,
      hint: geminiReady ? undefined : "Set GEMINI_API_KEY",
    },
    {
      id: "deepseek",
      label: "DeepSeek",
      icon: Zap,
      ready: deepseekReady,
      hint: deepseekReady ? undefined : "Set DEEPSEEK_API_KEY",
    },
  ]
  return (
    <div className="flex items-center gap-1 rounded-lg border bg-card p-1">
      {opts.map((o) => {
        const active = value === o.id
        const blocked = !o.ready
        return (
          <button
            key={o.id}
            title={o.hint}
            disabled={disabled || blocked}
            onClick={() => onChange(o.id)}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-40",
              active
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <o.icon className="size-3.5" />
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

const SUGGESTED = [
  "What are the main themes so far?",
  "Summarize each main character's arc.",
  "Which plot threads are still open?",
  "Where might a reader get confused?",
]

function Suggestions({ onPick }: { onPick: (s: string) => void }) {
  return (
    <div className="pt-8 text-center">
      <p className="mb-4 text-sm text-muted-foreground">
        Ask anything about your draft. For example:
      </p>
      <div className="mx-auto grid max-w-xl grid-cols-1 gap-2 sm:grid-cols-2">
        {SUGGESTED.map((s) => (
          <button
            key={s}
            onClick={() => onPick(s)}
            className="rounded-lg border px-4 py-3 text-left text-sm transition-colors hover:bg-accent/50"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}
