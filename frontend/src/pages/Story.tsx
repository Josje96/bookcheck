import { useBookcheck } from "@/lib/store"
import { type Chapter } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { EmptyManuscript, Loading, PageHeader } from "@/components/PageState"

function chapterLabel(ch: Chapter): string {
  if (!ch.pov_character) return "Prologue"
  const date = ch.date_label ? `, ${ch.date_label}` : ""
  return `Chapter ${ch.chapter_seq} - ${ch.pov_character}${date}`
}

export default function Story() {
  const { bible, loading } = useBookcheck()

  if (loading) return <Loading />
  if (!bible) return <EmptyManuscript />

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <PageHeader
        title="Story"
        subtitle="How your draft came across on a first read."
      />

      {bible.impression && (
        <Card className="mb-8 border-primary/30 bg-primary/5">
          <CardHeader>
            <CardTitle>Overall impression</CardTitle>
          </CardHeader>
          <CardContent className="whitespace-pre-wrap text-sm leading-relaxed">
            {bible.impression}
          </CardContent>
        </Card>
      )}

      <h2 className="mb-3 text-lg font-semibold">Chapter by chapter</h2>
      <div className="space-y-4">
        {bible.chapters.map((ch) => (
          <Card key={`${ch.chapter_seq}-${ch.pov_character ?? "pro"}`}>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">{chapterLabel(ch)}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="leading-relaxed">
                {ch.summary || (
                  <span className="text-muted-foreground">No summary.</span>
                )}
              </p>
              {ch.uncertainties.length > 0 && (
                <div className="rounded-md bg-muted/60 p-3">
                  <div className="mb-1.5 flex items-center gap-2">
                    <Badge variant="muted">Murky spots</Badge>
                    <span className="text-xs text-muted-foreground">
                      where the read stumbled - possibly unclear writing
                    </span>
                  </div>
                  <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                    {ch.uncertainties.map((u, i) => (
                      <li key={i}>{u}</li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {bible.locations.length > 0 && (
        <div className="mt-8">
          <h2 className="mb-2 text-lg font-semibold">Locations</h2>
          <div className="flex flex-wrap gap-2">
            {bible.locations.map((l) => (
              <Badge key={l.name} variant="secondary">
                {l.name}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
