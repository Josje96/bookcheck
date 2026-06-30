import { useMemo, useState } from "react"
import { useBookcheck } from "@/lib/store"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyManuscript, Loading, PageHeader } from "@/components/PageState"
import { Search, Users } from "lucide-react"

interface Edge {
  other: string
  relation: string
}

function groupedEdges(edges: Edge[]): [string, string[]][] {
  const map = new Map<string, string[]>()
  for (const e of edges) {
    const list = map.get(e.other) ?? []
    if (!list.includes(e.relation)) list.push(e.relation)
    map.set(e.other, list)
  }
  return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]))
}

export default function Relations() {
  const { bible, loading } = useBookcheck()
  const [query, setQuery] = useState("")

  const rels = bible?.relationships ?? []

  // Build an adjacency map so each character shows all of their relationships,
  // from either side of the extracted pair.
  const byCharacter = useMemo(() => {
    const map = new Map<string, Edge[]>()
    const add = (who: string, other: string, relation: string) => {
      const list = map.get(who) ?? []
      if (!list.some((e) => e.other === other && e.relation === relation))
        list.push({ other, relation })
      map.set(who, list)
    }
    for (const r of rels) {
      add(r.a, r.b, r.relation)
      add(r.b, r.a, r.relation)
    }
    return [...map.entries()]
      .map(([name, edges]) => ({ name, edges }))
      .sort((x, y) => y.edges.length - x.edges.length || x.name.localeCompare(y.name))
  }, [rels])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return byCharacter
    return byCharacter.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.edges.some(
          (e) =>
            e.other.toLowerCase().includes(q) ||
            e.relation.toLowerCase().includes(q),
        ),
    )
  }, [byCharacter, query])

  if (loading) return <Loading />
  if (!bible) return <EmptyManuscript />

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <PageHeader
        title="Relations"
        subtitle="Who's connected to whom: friends, family, love interests and more."
      />

      {byCharacter.length === 0 ? (
        <p className="text-muted-foreground">
          No relationships were extracted from this manuscript. Re-analyze to
          build them.
        </p>
      ) : (
        <>
          <div className="relative mb-5 max-w-md">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by character or relation..."
              className="w-full rounded-md border bg-background py-2 pl-9 pr-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
            {filtered.map((c) => (
              <Card key={c.name}>
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Users className="size-4 shrink-0 text-primary" />
                    {c.name}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3.5 text-sm">
                  {groupedEdges(c.edges).map(([other, relations], i) => (
                    <div key={i} className="flex items-start gap-3">
                      <span className="min-w-28 pt-0.5 font-medium text-foreground">
                        {other}
                      </span>
                      <div className="flex flex-wrap gap-1.5">
                        {relations.map((rel, j) => (
                          <Badge key={j} variant="muted">{rel}</Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            ))}
          </div>

          {filtered.length === 0 && (
            <p className="text-muted-foreground">
              No relationships match "{query.trim()}".
            </p>
          )}
        </>
      )}
    </div>
  )
}
