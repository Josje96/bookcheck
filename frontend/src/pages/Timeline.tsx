import { useMemo } from "react"
import { useBookcheck } from "@/lib/store"
import { type TimelineEvent } from "@/lib/api"
import { EmptyManuscript, Loading, PageHeader } from "@/components/PageState"

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

// "11-24 evening" -> "Nov 24 · evening"; "11-23" -> "Nov 23"; null -> "Unsequenced".
function formatWhen(when: string | null): string {
  if (!when) return "Unsequenced"
  const [head, ...rest] = when.trim().split(/\s+/)
  const m = head.match(/^(\d{1,2})-(\d{1,2})$/)
  let label = head
  if (m) {
    const month = MONTHS[Number(m[1]) - 1]
    label = month ? `${month} ${Number(m[2])}` : head
  }
  const phase = rest.join(" ")
  return phase ? `${label} · ${phase}` : label
}

interface Group {
  when: string | null
  label: string
  events: TimelineEvent[]
}

export default function Timeline() {
  const { bible, loading } = useBookcheck()

  const groups = useMemo<Group[]>(() => {
    const events = bible?.timeline ?? []
    const out: Group[] = []
    for (const e of events) {
      const last = out[out.length - 1]
      if (last && last.when === e.when) last.events.push(e)
      else out.push({ when: e.when, label: formatWhen(e.when), events: [e] })
    }
    return out
  }, [bible])

  if (loading) return <Loading />
  if (!bible) return <EmptyManuscript />

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <PageHeader
        title="Timeline"
        subtitle="In-story events in the order they happen, grouped by day."
      />

      {groups.length === 0 ? (
        <p className="text-muted-foreground">
          No timeline events were extracted from this manuscript.
        </p>
      ) : (
        <ol className="relative space-y-8">
          <div className="absolute bottom-2 left-[7px] top-2 w-px bg-border" />
          {groups.map((g, i) => (
            <li key={`${g.when ?? "none"}-${i}`} className="relative pl-8">
              <span className="absolute left-0 top-1 size-3.5 rounded-full border-2 border-primary bg-background" />
              <h3 className="text-sm font-semibold tracking-tight">{g.label}</h3>
              <ul className="mt-2 space-y-2">
                {g.events.map((e, j) => (
                  <li key={j} className="text-sm leading-relaxed">
                    {e.event}
                    {e.ref && (
                      <span className="ml-2 text-xs text-muted-foreground">
                        {e.ref}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
