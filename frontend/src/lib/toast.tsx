import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react"
import { CheckCircle2, AlertCircle, X } from "lucide-react"
import { cn } from "@/lib/utils"

type ToastKind = "success" | "error" | "info"

interface Toast {
  id: number
  kind: ToastKind
  title: string
  description?: string
}

interface ToastApi {
  toast: (t: { kind?: ToastKind; title: string; description?: string }) => void
}

const Ctx = createContext<ToastApi | null>(null)

let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const dismiss = useCallback((id: number) => {
    setToasts((ts) => ts.filter((t) => t.id !== id))
  }, [])

  const toast = useCallback<ToastApi["toast"]>(({ kind = "info", title, description }) => {
    const id = nextId++
    setToasts((ts) => [...ts, { id, kind, title, description }])
  }, [])

  return (
    <Ctx.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2">
        {toasts.map((t) => (
          <ToastCard key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </Ctx.Provider>
  )
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  // Auto-dismiss; success/info are transient, errors linger a bit longer.
  useEffect(() => {
    const ms = toast.kind === "error" ? 8000 : 5000
    const id = window.setTimeout(onDismiss, ms)
    return () => window.clearTimeout(id)
  }, [toast.kind, onDismiss])

  const Icon = toast.kind === "error" ? AlertCircle : CheckCircle2
  return (
    <div
      className={cn(
        "pointer-events-auto flex items-start gap-3 rounded-lg border bg-card p-3 shadow-lg",
        toast.kind === "error" && "border-destructive/40",
        toast.kind === "success" && "border-emerald-500/40",
      )}
    >
      <Icon
        className={cn(
          "mt-0.5 size-5 shrink-0",
          toast.kind === "error" ? "text-destructive" : "text-emerald-500",
        )}
      />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{toast.title}</p>
        {toast.description && (
          <p className="mt-0.5 text-sm text-muted-foreground">{toast.description}</p>
        )}
      </div>
      <button
        onClick={onDismiss}
        className="text-muted-foreground transition-colors hover:text-foreground"
        aria-label="Dismiss"
      >
        <X className="size-4" />
      </button>
    </div>
  )
}

export function useToast(): ToastApi {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error("useToast must be used within ToastProvider")
  return ctx
}
