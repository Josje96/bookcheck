import { useEffect, useRef, useState } from "react"
import {
  Loader2,
  Upload,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
} from "lucide-react"
import { api, type RunStatus, type Provider } from "@/lib/api"
import { useBookcheck } from "@/lib/store"
import { useToast } from "@/lib/toast"
import { formatDuration, engineLabel } from "@/lib/format"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { cn } from "@/lib/utils"

// Analysis engine = provider + model. `model` maps to the extract-model
// override for Ollama, or the Gemini model id for Gemini. Add a provider by
// appending here (and a matching branch in bookcheck/providers.py).
type Engine = {
  id: string
  label: string
  provider: Provider
  model: string
  needsGemini?: boolean
  needsDeepseek?: boolean
}

const ENGINES: Engine[] = [
  { id: "ollama:", label: "Local - qwen3:4b (faster)", provider: "ollama", model: "" },
  { id: "ollama:qwen3:8b", label: "Local - qwen3:8b (higher quality)", provider: "ollama", model: "qwen3:8b" },
  { id: "gemini:", label: "Gemini 2.5 Flash (cloud, fast)", provider: "gemini", model: "", needsGemini: true },
  { id: "deepseek:deepseek-v4-flash", label: "DeepSeek V4 Flash (cloud, fast)", provider: "deepseek", model: "deepseek-v4-flash", needsDeepseek: true },
  { id: "deepseek:deepseek-v4-pro", label: "DeepSeek V4 Pro (cloud, best)", provider: "deepseek", model: "deepseek-v4-pro", needsDeepseek: true },
]

export default function RunControls({
  hasManuscript,
  hasSource,
  geminiReady,
  deepseekReady,
}: {
  hasManuscript: boolean
  hasSource: boolean
  geminiReady: boolean
  deepseekReady: boolean
}) {
  const { refresh } = useBookcheck()
  const { toast } = useToast()
  const [file, setFile] = useState<File | null>(null)
  const [text, setText] = useState("")
  const [engineId, setEngineId] = useState("ollama:")
  const [deep, setDeep] = useState(false)
  const [run, setRun] = useState<RunStatus | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const pollRef = useRef<number | null>(null)
  // The engine label for the in-flight run, captured at start so the
  // completion toast is correct even if the dropdown changes meanwhile.
  const runLabelRef = useRef<string>("")

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [])

  function poll(id: string) {
    if (pollRef.current) window.clearInterval(pollRef.current)
    pollRef.current = window.setInterval(async () => {
      try {
        const s = await api.run(id)
        setRun(s)
        if (s.status === "done") {
          window.clearInterval(pollRef.current!)
          setSubmitting(false)
          toast({
            kind: "success",
            title: "Analysis complete",
            description: `Read with ${runLabelRef.current} in ${formatDuration(
              s.elapsed_s,
            )}.`,
          })
          await refresh()
        } else if (s.status === "error") {
          window.clearInterval(pollRef.current!)
          setSubmitting(false)
          setErr(s.error ?? "Analysis failed.")
          toast({
            kind: "error",
            title: "Analysis failed",
            description: s.error ?? "Something went wrong during the run.",
          })
        }
      } catch {
        /* transient; keep polling */
      }
    }, 1500)
  }

  async function start(opts: { reuse?: boolean } = {}) {
    setErr(null)
    if (!opts.reuse && !file && !text.trim()) {
      setErr("Pick a manuscript file or paste some text first.")
      return
    }
    setSubmitting(true)
    try {
      const engine = ENGINES.find((e) => e.id === engineId) ?? ENGINES[0]
      runLabelRef.current = engineLabel(engine.provider, engine.model)
      const form = new FormData()
      if (opts.reuse) form.append("reuse", "true")
      else if (file) form.append("file", file)
      else form.append("text", text)
      form.append("provider", engine.provider)
      if (engine.model) form.append("extract_model", engine.model)
      if (deep) form.append("deep", "true")
      const started = await api.startRun(form)
      setRun(started)
      poll(started.id!)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      setSubmitting(false)
    }
  }

  const running = run && (run.status === "running" || run.status === "queued")

  return (
    <Card className="mx-auto max-w-2xl">
      <CardHeader>
        <CardTitle className="text-xl">
          {hasManuscript ? "Re-analyze" : "Analyze a manuscript"}
        </CardTitle>
        <CardDescription>
          {hasManuscript
            ? "Re-run the current manuscript with a different model, or upload a new one. Re-running replaces the existing analysis."
            : "Upload a .txt/.md/.docx/.pdf file (or paste your draft). bookcheck reads it locally and builds your story bible - nothing leaves this machine."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {running && run ? (
          <Progress run={run} />
        ) : (
          <>
            <EngineOptions
              engineId={engineId}
              setEngineId={setEngineId}
              deep={deep}
              setDeep={setDeep}
              geminiReady={geminiReady}
              deepseekReady={deepseekReady}
            />

            {hasSource && (
              <Button
                variant="secondary"
                className="w-full"
                disabled={submitting}
                onClick={() => start({ reuse: true })}
              >
                <RefreshCw /> Re-run on current manuscript
              </Button>
            )}

            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <div className="h-px flex-1 bg-border" />
              {hasSource ? "or upload a different manuscript" : "upload"}
              <div className="h-px flex-1 bg-border" />
            </div>

            <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground hover:bg-accent/40">
              <Upload className="size-6" />
              {file ? (
                <span className="font-medium text-foreground">{file.name}</span>
              ) : (
                <span>Click to choose a manuscript file</span>
              )}
              <input
                type="file"
                accept=".txt,.md,.docx,.pdf,text/plain,text/markdown,application/pdf"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>

            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="…or paste your manuscript here"
              rows={4}
              className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />

            <Button
              onClick={() => start()}
              disabled={submitting}
              className="w-full"
            >
              {submitting ? <Loader2 className="animate-spin" /> : <Upload />}
              {hasManuscript ? "Analyze new manuscript" : "Analyze manuscript"}
            </Button>
            <p className="text-center text-xs text-muted-foreground">
              A full read can take several minutes on a local GPU.
            </p>
          </>
        )}

        {err && (
          <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            <AlertCircle className="mt-0.5 size-4 shrink-0" />
            <span>{err}</span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function EngineOptions({
  engineId,
  setEngineId,
  deep,
  setDeep,
  geminiReady,
  deepseekReady,
}: {
  engineId: string
  setEngineId: (v: string) => void
  deep: boolean
  setDeep: (v: boolean) => void
  geminiReady: boolean
  deepseekReady: boolean
}) {
  return (
    <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">
          Analysis engine
        </label>
        <select
          value={engineId}
          onChange={(e) => setEngineId(e.target.value)}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {ENGINES.filter(
            (m) =>
              (!m.needsGemini || geminiReady) &&
              (!m.needsDeepseek || deepseekReady),
          ).map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">
          Cloud engines are faster and higher-quality but send your manuscript to
          the provider. Local stays on this machine.
        </p>
      </div>
      <label className="flex cursor-pointer items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={deep}
          onChange={(e) => setDeep(e.target.checked)}
          className="size-4 rounded border"
        />
        <span>
          Deep pass{" "}
          <span className="text-muted-foreground">
            - extra whole-book reasoning (slower, noisier)
          </span>
        </span>
      </label>
    </div>
  )
}

function Progress({ run }: { run: RunStatus }) {
  const steps = run.steps ?? []
  const current = run.step_index ?? 0
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Loader2 className="size-4 animate-spin text-primary" />
        {run.message}
        {run.elapsed_s ? (
          <span className="text-muted-foreground">· {run.elapsed_s}s</span>
        ) : null}
      </div>
      <ol className="space-y-1.5">
        {steps.map((s, i) => {
          const done = i < current
          const active = i === current
          return (
            <li
              key={s.key}
              className={cn(
                "flex items-center gap-2 text-sm",
                done && "text-muted-foreground",
                active && "font-medium text-foreground",
                !done && !active && "text-muted-foreground/60",
              )}
            >
              {done ? (
                <CheckCircle2 className="size-4 text-emerald-500" />
              ) : active ? (
                <Loader2 className="size-4 animate-spin text-primary" />
              ) : (
                <span className="size-4 rounded-full border" />
              )}
              {s.label}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
