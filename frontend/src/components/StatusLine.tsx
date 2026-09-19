import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import type { ProfilePhase } from './ProgressLine'
import { t, type Lang } from '../i18n'
import { formatAgo, formatSeconds } from '../lib/format'
import Icon from './Icon'

interface Props {
  phase: ProfilePhase
  elapsedMs: number
  totalMs: number | null
  cachedAt: string | null
  lang: Lang
  onRefresh?: () => void
}

/** The status pill: a pulsing dot and one sentence per stage with live elapsed seconds while
 *  the stream is open; a check mark and «Профиль готов за 20,4 с» when done; the cached
 *  sentence plus a refresh action when served from the cache. aria-live for screen readers. */
export default function StatusLine({ phase, elapsedMs, totalMs, cachedAt, lang, onRefresh }: Props) {
  const reduced = useReducedMotion() ?? false
  if (phase === 'error') return null
  const running = phase !== 'done'
  const sentence =
    phase === 'done'
      ? cachedAt
        ? t(lang, 'status_cached', { ago: formatAgo(cachedAt, lang) })
        : t(lang, 'status_done', { seconds: formatSeconds(totalMs ?? elapsedMs, lang) })
      : t(lang, `status_${phase}`)

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div
        className="inline-flex items-center gap-3 min-h-9 pl-3 pr-4 py-1 rounded-full bg-surface border border-line shadow-card text-[14px] text-ink-2"
        aria-live="polite"
        aria-atomic="true"
      >
        {running ? (
          <span className="live-dot" aria-hidden="true" />
        ) : (
          <span className="vdot vdot-verified" aria-hidden="true">
            <Icon name="check" size={11} strokeWidth={2.5} />
          </span>
        )}
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={sentence}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1, transition: { duration: reduced ? 0 : 0.2 } }}
            exit={{ opacity: 0, transition: { duration: reduced ? 0 : 0.12 } }}
            className="inline"
          >
            {sentence}
            {running && <span className="num text-ink"> {formatSeconds(elapsedMs, lang)}</span>}
          </motion.span>
        </AnimatePresence>
      </div>
      {phase === 'done' && cachedAt && onRefresh && (
        <button type="button" className="btn btn-ghost btn-sm" onClick={onRefresh}>
          <Icon name="refresh" size={15} />
          {t(lang, 'masthead_refresh')}
        </button>
      )}
    </div>
  )
}
