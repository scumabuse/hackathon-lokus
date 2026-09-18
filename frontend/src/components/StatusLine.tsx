import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import type { ProfilePhase } from './ProgressLine'
import { t, type Lang } from '../i18n'
import { formatAgo, formatSeconds } from '../lib/format'

interface Props {
  phase: ProfilePhase
  elapsedMs: number
  totalMs: number | null
  cachedAt: string | null
  lang: Lang
}

/** One sentence that changes by stage, with live elapsed seconds (B5.3); aria-live. */
export default function StatusLine({ phase, elapsedMs, totalMs, cachedAt, lang }: Props) {
  const reduced = useReducedMotion() ?? false
  let sentence: string
  if (phase === 'done') {
    sentence = cachedAt
      ? t(lang, 'status_cached', { ago: formatAgo(cachedAt, lang) })
      : t(lang, 'status_done', { seconds: formatSeconds(totalMs ?? elapsedMs, lang) })
  } else if (phase === 'error') {
    sentence = ''
  } else {
    sentence = t(lang, `status_${phase}`)
  }
  const running = phase !== 'done' && phase !== 'error'
  return (
    <p className="mt-6 text-[15px] text-ink-2 min-h-[1.5em]" aria-live="polite" aria-atomic="true">
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={sentence}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1, transition: { duration: reduced ? 0 : 0.2 } }}
          exit={{ opacity: 0, transition: { duration: reduced ? 0 : 0.12 } }}
          className="inline"
        >
          {sentence}
          {running && (
            <span className="tabular-nums">
              {' '}
              {formatSeconds(elapsedMs, lang)}
            </span>
          )}
        </motion.span>
      </AnimatePresence>
    </p>
  )
}
