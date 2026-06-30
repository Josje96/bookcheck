// Small display formatters shared across pages.

/** 95 -> "1m 35s", 42 -> "42s", 3700 -> "1h 2m". */
export function formatDuration(seconds: number | null | undefined): string {
  const s = Math.max(0, Math.round(seconds ?? 0))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) {
    const rem = s % 60
    return rem ? `${m}m ${rem}s` : `${m}m`
  }
  const h = Math.floor(m / 60)
  const remM = m % 60
  return remM ? `${h}h ${remM}m` : `${h}h`
}

/** Epoch seconds -> "just now" / "5m ago" / "2h ago" / a short date. */
export function relativeTime(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) return ""
  const diff = Date.now() / 1000 - epochSeconds
  if (diff < 60) return "just now"
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 7 * 86400) return `${Math.floor(diff / 86400)}d ago`
  return new Date(epochSeconds * 1000).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  })
}

/** Friendly engine name from a run's provider + model. */
export function engineLabel(
  provider: string | null | undefined,
  model: string | null | undefined,
): string {
  if (provider === "gemini") return "Gemini"
  if (provider === "deepseek") return model || "DeepSeek"
  return model || "qwen3:4b"
}
