import { NavLink, Outlet } from "react-router-dom"
import {
  BookOpenText,
  MessagesSquare,
  Users,
  Network,
  MapPin,
  ScrollText,
  CalendarClock,
  FileText,
  LayoutDashboard,
  Sun,
  Moon,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useBookcheck } from "@/lib/store"
import { THEMES, useTheme } from "@/lib/theme"

const NAV = [
  { to: "/", label: "Home", icon: LayoutDashboard, end: true },
  { to: "/chat", label: "Chat", icon: MessagesSquare },
  { to: "/characters", label: "Characters", icon: Users },
  { to: "/relations", label: "Relations", icon: Network },
  { to: "/locations", label: "Locations", icon: MapPin },
  { to: "/story", label: "Story", icon: ScrollText },
  { to: "/timeline", label: "Timeline", icon: CalendarClock },
  { to: "/report", label: "Report", icon: FileText },
]

function ThemeControls() {
  const { mode, toggleMode, theme, setTheme } = useTheme()
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border bg-card p-2">
      <div className="flex items-center gap-1.5">
        {THEMES.map((t) => (
          <button
            key={t.id}
            title={t.label}
            onClick={() => setTheme(t.id)}
            style={{ background: t.swatch }}
            className={cn(
              "size-5 rounded-full border transition-transform hover:scale-110",
              theme === t.id
                ? "ring-2 ring-ring ring-offset-1 ring-offset-card"
                : "opacity-70",
            )}
          />
        ))}
      </div>
      <button
        onClick={toggleMode}
        title={mode === "dark" ? "Switch to light" : "Switch to dark"}
        className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        {mode === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
      </button>
    </div>
  )
}

function UserBadge() {
  const { health } = useBookcheck()
  const name = health?.username?.trim()
  if (!name) return null
  return (
    <div className="flex items-center gap-2">
      <div className="flex size-7 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary">
        {name.slice(0, 1).toUpperCase()}
      </div>
      <span className="truncate text-sm font-medium">{name}</span>
    </div>
  )
}

function HealthDot() {
  const { health } = useBookcheck()
  const ok = health?.ollama
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span
        className={cn(
          "size-2 rounded-full",
          ok === undefined
            ? "bg-muted-foreground/40"
            : ok
              ? "bg-emerald-500"
              : "bg-destructive",
        )}
      />
      {ok === undefined
        ? "Checking…"
        : ok
          ? "Ollama connected"
          : "Ollama offline"}
    </div>
  )
}

export default function Layout() {
  return (
    <div className="flex h-full">
      <aside className="flex w-60 flex-col border-r bg-card/40 px-3 py-5">
        <div className="flex items-center gap-2 px-2 pb-6">
          <BookOpenText className="size-6 text-primary" />
          <span className="text-lg font-semibold tracking-tight">bookcheck</span>
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                )
              }
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="space-y-3 px-3 pt-4">
          <ThemeControls />
          <UserBadge />
          <HealthDot />
        </div>
      </aside>
      <main className="h-full flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
