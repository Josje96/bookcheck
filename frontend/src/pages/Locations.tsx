import { useMemo, useState } from "react"
import { useBookcheck } from "@/lib/store"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyManuscript, Loading, PageHeader } from "@/components/PageState"
import { MapPin, Search } from "lucide-react"

export default function Locations() {
  const { bible, loading } = useBookcheck()
  const [query, setQuery] = useState("")

  const locations = bible?.locations ?? []
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return locations
    return locations.filter((l) =>
      `${l.name} ${l.description ?? ""}`.toLowerCase().includes(q),
    )
  }, [locations, query])

  if (loading) return <Loading />
  if (!bible) return <EmptyManuscript />

  return (
    <div className="mx-auto max-w-5xl px-8 py-10">
      <PageHeader
        title="Locations"
        subtitle={`${locations.length} place${
          locations.length === 1 ? "" : "s"
        } found in your draft.`}
      />

      {locations.length === 0 ? (
        <p className="text-muted-foreground">
          No locations were extracted from this manuscript. Re-analyze to build
          them.
        </p>
      ) : (
        <>
          <div className="relative mb-5 max-w-md">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search locations..."
              className="w-full rounded-md border bg-background py-2 pl-9 pr-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="grid grid-cols-1 items-start gap-4 sm:grid-cols-2">
            {filtered.map((l) => (
              <Card key={l.name}>
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <MapPin className="size-4 shrink-0 text-primary" />
                    {l.name}
                  </CardTitle>
                </CardHeader>
                {l.description && (
                  <CardContent className="text-sm text-muted-foreground">
                    {l.description}
                  </CardContent>
                )}
              </Card>
            ))}
          </div>

          {filtered.length === 0 && (
            <p className="text-muted-foreground">
              No locations match "{query.trim()}".
            </p>
          )}
        </>
      )}
    </div>
  )
}
