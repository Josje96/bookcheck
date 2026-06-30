import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react"

// Accent themes. To add one: append here AND add matching CSS blocks
// ([data-theme="<id>"] + .dark[data-theme="<id>"]) in index.css. "violet" is
// the base defined in :root, so it needs no extra CSS.
export const THEMES = [
  { id: "base", label: "Base (neutral)", swatch: "oklch(0.6 0 0)" },
  { id: "violet", label: "Violet", swatch: "oklch(0.52 0.18 285)" },
  { id: "emerald", label: "Emerald", swatch: "oklch(0.55 0.13 155)" },
  { id: "amber", label: "Amber", swatch: "oklch(0.66 0.15 70)" },
  { id: "rose", label: "Rose", swatch: "oklch(0.58 0.18 15)" },
] as const

export type ThemeId = (typeof THEMES)[number]["id"]
export type Mode = "light" | "dark"

const MODE_KEY = "bc-mode"
const THEME_KEY = "bc-theme"

interface ThemeState {
  mode: Mode
  theme: ThemeId
  setMode: (m: Mode) => void
  toggleMode: () => void
  setTheme: (t: ThemeId) => void
}

const Ctx = createContext<ThemeState | null>(null)

function initialMode(): Mode {
  const saved = localStorage.getItem(MODE_KEY)
  if (saved === "light" || saved === "dark") return saved
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light"
}

function initialTheme(): ThemeId {
  const saved = localStorage.getItem(THEME_KEY)
  return (THEMES.find((t) => t.id === saved)?.id ?? "violet") as ThemeId
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<Mode>(initialMode)
  const [theme, setThemeState] = useState<ThemeId>(initialTheme)

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle("dark", mode === "dark")
    root.dataset.theme = theme
  }, [mode, theme])

  const setMode = useCallback((m: Mode) => {
    localStorage.setItem(MODE_KEY, m)
    setModeState(m)
  }, [])

  const toggleMode = useCallback(() => {
    setMode(mode === "dark" ? "light" : "dark")
  }, [mode, setMode])

  const setTheme = useCallback((t: ThemeId) => {
    localStorage.setItem(THEME_KEY, t)
    setThemeState(t)
  }, [])

  return (
    <Ctx.Provider value={{ mode, theme, setMode, toggleMode, setTheme }}>
      {children}
    </Ctx.Provider>
  )
}

export function useTheme() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider")
  return ctx
}
