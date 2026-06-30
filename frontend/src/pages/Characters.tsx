import { useMemo, useState } from "react"
import { useBookcheck } from "@/lib/store"
import { type Character, type Trait } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyManuscript, Loading, PageHeader } from "@/components/PageState"
import { ChevronDown, ChevronRight, Search } from "lucide-react"

const ROLE_VARIANT: Record<string, "default" | "secondary" | "muted"> = {
  main: "default",
  supporting: "secondary",
  minor: "muted",
}

type FieldKey = "description" | "arc" | "strengths" | "weaknesses" | "development"
type ViewKey = "all" | "traits" | FieldKey

// Order the detail sections appear in. `description` doubles as the "Summary".
const FIELDS: { key: FieldKey; label: string }[] = [
  { key: "description", label: "Summary" },
  { key: "arc", label: "Arc" },
  { key: "strengths", label: "Strengths" },
  { key: "weaknesses", label: "Weaknesses" },
  { key: "development", label: "To develop" },
]

const VIEW_OPTIONS: { value: ViewKey; label: string }[] = [
  { value: "all", label: "All sections" },
  { value: "traits", label: "Appearance & traits" },
  ...FIELDS.map((f) => ({ value: f.key, label: f.label })),
]

// "eye_color" / "owns:cottage" -> "eye color" / "owns cottage" for display.
function prettyAttr(attr: string): string {
  return attr.replace(/[_:]+/g, " ").trim()
}

function hasDetail(c: Character): boolean {
  return Boolean(
    c.description ||
      c.arc ||
      c.strengths ||
      c.weaknesses ||
      c.development ||
      (c.traits && c.traits.length > 0),
  )
}

export default function Characters() {
  const { bible, loading } = useBookcheck()
  const [query, setQuery] = useState("")
  const [view, setView] = useState<ViewKey>("all")
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const characters = bible?.characters ?? []

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return characters
    return characters.filter((c) => {
      const hay = [
        c.name, c.role, c.species, c.description, c.arc,
        c.strengths, c.weaknesses, c.development,
        ...(c.aliases ?? []),
        ...(c.traits ?? []).flatMap((t) => [t.attribute, t.value]),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
      return hay.includes(q)
    })
  }, [characters, query])

  if (loading) return <Loading />
  if (!bible) return <EmptyManuscript />

  const allOpen = filtered.length > 0 && filtered.every((c) => expanded.has(c.name))

  function toggleAll() {
    setExpanded(allOpen ? new Set() : new Set(filtered.map((c) => c.name)))
  }
  function toggle(name: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <PageHeader
        title="Characters"
        subtitle={`${characters.length} characters found in your draft.`}
      />

      {characters.length > 0 && (
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search characters..."
              className="w-full rounded-md border bg-background py-2 pl-9 pr-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          <select
            value={view}
            onChange={(e) => setView(e.target.value as ViewKey)}
            aria-label="Choose which sections to show"
            className="rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {VIEW_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                Show: {o.label}
              </option>
            ))}
          </select>
          <Button
            variant="outline"
            size="sm"
            onClick={toggleAll}
            disabled={filtered.length === 0}
          >
            {allOpen ? "Collapse all" : "Expand all"}
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
        {filtered.map((c) => (
          <CharacterCard
            key={c.name}
            c={c}
            view={view}
            open={expanded.has(c.name)}
            onToggle={() => toggle(c.name)}
          />
        ))}
      </div>

      {characters.length === 0 && (
        <p className="text-muted-foreground">No characters with recorded detail.</p>
      )}
      {characters.length > 0 && filtered.length === 0 && (
        <p className="text-muted-foreground">
          No characters match "{query.trim()}".
        </p>
      )}
    </div>
  )
}

function CharacterCard({
  c,
  view,
  open,
  onToggle,
}: {
  c: Character
  view: ViewKey
  open: boolean
  onToggle: () => void
}) {
  return (
    <Card>
      <CardHeader className="p-0">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex w-full items-center gap-2 rounded-xl px-6 py-4 text-left transition-colors hover:bg-accent/50"
        >
          {open ? (
            <ChevronDown className="mt-1 size-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="mt-1 size-4 shrink-0 text-muted-foreground" />
          )}
          <div className="flex-1">
            <CardTitle className="flex flex-wrap items-center gap-2">
              {c.name}
              {c.role && (
                <Badge variant={ROLE_VARIANT[c.role] ?? "muted"}>{c.role}</Badge>
              )}
              {c.species && <Badge variant="outline">{c.species}</Badge>}
            </CardTitle>
            {c.aliases && c.aliases.length > 0 && (
              <p className="mt-1 text-xs font-normal text-muted-foreground">
                aka {c.aliases.join(", ")}
              </p>
            )}
          </div>
        </button>
      </CardHeader>

      {open && (
        <CardContent className="space-y-3 text-sm">
          {view === "all" ? (
            <>
              {c.description && <p>{c.description}</p>}
              <TraitsBlock traits={c.traits} />
              <div className="grid gap-2">
                <Field label="Arc" value={c.arc} />
                <Field label="Strengths" value={c.strengths} />
                <Field label="Weaknesses" value={c.weaknesses} />
                <Field label="To develop" value={c.development} />
              </div>
              {!hasDetail(c) && (
                <p className="text-muted-foreground">No details recorded.</p>
              )}
            </>
          ) : view === "traits" ? (
            c.traits && c.traits.length > 0 ? (
              <TraitsBlock traits={c.traits} hideLabel />
            ) : (
              <p className="text-muted-foreground">
                No appearance or traits recorded for {c.name}.
              </p>
            )
          ) : (
            <SingleSection c={c} view={view} />
          )}
        </CardContent>
      )}
    </Card>
  )
}

function TraitsBlock({
  traits,
  hideLabel,
}: {
  traits: Trait[]
  hideLabel?: boolean
}) {
  if (!traits || traits.length === 0) return null
  return (
    <div>
      {!hideLabel && (
        <p className="mb-1.5 font-medium text-muted-foreground">
          Appearance & traits
        </p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {traits.map((t, i) => (
          <span
            key={i}
            className="rounded-md border bg-muted/40 px-2 py-0.5 text-xs"
          >
            <span className="text-muted-foreground">{prettyAttr(t.attribute)}: </span>
            {t.value}
          </span>
        ))}
      </div>
    </div>
  )
}

function SingleSection({ c, view }: { c: Character; view: FieldKey }) {
  const label = FIELDS.find((f) => f.key === view)!.label
  const value = c[view]
  if (!value) {
    return (
      <p className="text-muted-foreground">
        No {label.toLowerCase()} recorded for {c.name}.
      </p>
    )
  }
  return <Field label={label} value={value} />
}

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null
  return (
    <p>
      <span className="font-medium text-muted-foreground">{label}: </span>
      {value}
    </p>
  )
}
