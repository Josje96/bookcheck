import { Link } from "react-router-dom"
import { Loader2 } from "lucide-react"
import type { ReactNode } from "react"

export function Loading() {
  return (
    <div className="flex h-full items-center justify-center text-muted-foreground">
      <Loader2 className="mr-2 size-5 animate-spin" /> Loading…
    </div>
  )
}

export function EmptyManuscript() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground">
      <p>No manuscript analyzed yet.</p>
      <Link to="/" className="text-primary underline">
        Analyze one first
      </Link>
    </div>
  )
}

export function PageHeader({
  title,
  subtitle,
}: {
  title: string
  subtitle?: ReactNode
}) {
  return (
    <header className="mb-6">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {subtitle && (
        <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
      )}
    </header>
  )
}
