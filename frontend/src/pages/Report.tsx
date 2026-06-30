import { useEffect, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Download } from "lucide-react"
import { api } from "@/lib/api"
import { useBookcheck } from "@/lib/store"
import { Button } from "@/components/ui/button"
import { EmptyManuscript, Loading, PageHeader } from "@/components/PageState"

export default function Report() {
  const { health } = useBookcheck()
  const [md, setMd] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    api
      .report()
      .then((t) => alive && setMd(t))
      .catch((e) => alive && setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])

  if (loading) return <Loading />
  if (!health?.has_manuscript) return <EmptyManuscript />
  if (err || !md)
    return (
      <div className="mx-auto max-w-3xl px-8 py-10 text-muted-foreground">
        {err ?? "No report available."}
      </div>
    )

  function download() {
    const blob = new Blob([md!], { type: "text/markdown" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = "report.md"
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="mb-6 flex items-center justify-between">
        <PageHeader title="Report" />
        <Button variant="outline" size="sm" onClick={download}>
          <Download /> Download .md
        </Button>
      </div>
      <article className="markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
      </article>
    </div>
  )
}
