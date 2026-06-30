import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react"
import { api, type Bible, type Health } from "@/lib/api"

interface BookcheckState {
  health: Health | null
  bible: Bible | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

const Ctx = createContext<BookcheckState | null>(null)

export function BookcheckProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null)
  const [bible, setBible] = useState<Bible | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const h = await api.health()
      setHealth(h)
      if (h.has_manuscript) {
        setBible(await api.bible())
      } else {
        setBible(null)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return (
    <Ctx.Provider value={{ health, bible, loading, error, refresh }}>
      {children}
    </Ctx.Provider>
  )
}

export function useBookcheck() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error("useBookcheck must be used within BookcheckProvider")
  return ctx
}
