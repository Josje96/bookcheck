import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  MessagesSquare,
  Users,
  Network,
  MapPin,
  ScrollText,
  FileText,
  CalendarClock,
  Loader2,
  ArrowRight,
  AlertTriangle,
  RefreshCw,
  X,
} from "lucide-react"
import { useBookcheck } from "@/lib/store"
import { api, type RunStatus } from "@/lib/api"
import { relativeTime, formatDuration, engineLabel } from "@/lib/format"
import RunControls from "@/components/UploadPanel"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

const SECTIONS = [
  {
    to: "/chat",
    icon: MessagesSquare,
    title: "Chat",
    desc: "Ask questions about your draft - grounded in the story bible.",
  },
  {
    to: "/characters",
    icon: Users,
    title: "Characters",
    desc: "Profiles, roles, arcs, strengths and weaknesses.",
  },
  {
    to: "/relations",
    icon: Network,
    title: "Relations",
    desc: "Who's connected to whom: family, friends, love interests.",
  },
  {
    to: "/locations",
    icon: MapPin,
    title: "Locations",
    desc: "The places your story happens, with descriptions.",
  },
  {
    to: "/story",
    icon: ScrollText,
    title: "Story",
    desc: "Overall impression and a chapter-by-chapter read-through.",
  },
  {
    to: "/timeline",
    icon: CalendarClock,
    title: "Timeline",
    desc: "In-story events laid out in the order they happen.",
  },
  {
    to: "/report",
    icon: FileText,
    title: "Report",
    desc: "The full written report, including things to fix.",
  },
]

export default function Home() {
  const { health, bible, loading, error } = useBookcheck()
  const [showReanalyze, setShowReanalyze] = useState(false)
  const [lastRun, setLastRun] = useState<RunStatus | null>(null)

  // Refetch the latest run whenever the analysis changes (a re-run updates
  // `bible` via refresh()), so the "last analyzed" note stays current.
  useEffect(() => {
    if (!health?.has_manuscript) return
    api
      .latestRun()
      .then((r) => setLastRun(r.status === "done" ? r : null))
      .catch(() => setLastRun(null))
  }, [health?.has_manuscript, bible])

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 size-5 animate-spin" /> Loading…
      </div>
    )
  }

  const name = health?.username?.trim()

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            {name ? `${name}'s manuscript, read.` : "Your manuscript, read."}
          </h1>
          <p className="mt-1 text-muted-foreground">
            A private first-pass read of your novel - everything below comes from
            your own draft.
          </p>
          {lastRun && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
              <CalendarClock className="size-3.5" />
              Last analyzed {relativeTime(lastRun.finished_at)} with{" "}
              {engineLabel(lastRun.provider, lastRun.model)}
              {lastRun.elapsed_s
                ? ` in ${formatDuration(lastRun.elapsed_s)}`
                : ""}
            </p>
          )}
        </div>
        {health?.has_manuscript && (
          <Button
            variant="outline"
            onClick={() => setShowReanalyze((s) => !s)}
          >
            {showReanalyze ? <X /> : <RefreshCw />}
            {showReanalyze ? "Close" : "Re-analyze"}
          </Button>
        )}
      </header>

      {error && (
        <div className="mb-6 flex items-start gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {!health?.has_manuscript || !bible ? (
        <RunControls
          hasManuscript={false}
          hasSource={!!health?.has_source}
          geminiReady={!!health?.gemini_configured}
          deepseekReady={!!health?.deepseek_configured}
        />
      ) : (
        <>
          {showReanalyze && (
            <div className="mb-8">
              <RunControls
                hasManuscript
                hasSource={!!health.has_source}
                geminiReady={!!health.gemini_configured}
                deepseekReady={!!health.deepseek_configured}
              />
            </div>
          )}
          <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <Stat label="Chapters read" value={bible.meta.chapters} />
            <Stat label="Characters" value={bible.meta.characters} />
            <Stat label="Locations" value={bible.locations.length} />
            <Stat label="Relations" value={bible.relationships.length} />
            <Stat
              label="Flagged contradictions"
              value={bible.contradictions.length}
              warn={bible.contradictions.length > 0}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {SECTIONS.map(({ to, icon: Icon, title, desc }) => (
              <Link key={to} to={to} className="group">
                <Card className="h-full transition-colors hover:border-primary/50 hover:bg-accent/30">
                  <CardHeader>
                    <div className="mb-2 flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <Icon className="size-5" />
                    </div>
                    <CardTitle className="flex items-center justify-between">
                      {title}
                      <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                    </CardTitle>
                    <CardDescription>{desc}</CardDescription>
                  </CardHeader>
                </Card>
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function Stat({
  label,
  value,
  warn,
}: {
  label: string
  value: number
  warn?: boolean
}) {
  return (
    <Card>
      <CardContent className="p-5">
        <div
          className={
            warn ? "text-3xl font-semibold text-destructive" : "text-3xl font-semibold"
          }
        >
          {value}
        </div>
        <div className="mt-1 text-sm text-muted-foreground">{label}</div>
      </CardContent>
    </Card>
  )
}
