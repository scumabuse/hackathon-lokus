import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { t, type Lang } from '../i18n'

export type ProfilePhase = 'connecting' | 'searching' | 'verifying' | 'sorting' | 'done' | 'error'

const PERCENT: Record<ProfilePhase, number> = {
  connecting: 15,
  searching: 45,
  verifying: 60,
  sorting: 90,
  done: 100,
  error: 100,
}

/** 2px red line across the very top (B5.1); width by stage, fades 600 ms after done. */
export default function ProgressLine({ phase, lang }: { phase: ProfilePhase; lang: Lang }) {
  const reduced = useReducedMotion() ?? false
  const percent = PERCENT[phase]
  return (
    <AnimatePresence>
      {phase !== 'done' && phase !== 'error' && (
        <motion.div
          key="progress"
          role="progressbar"
          aria-label={t(lang, 'progress_aria')}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          className="fixed top-0 left-0 z-50 h-[2px] bg-mark"
          initial={{ width: '0%' }}
          animate={{ width: `${percent}%`, opacity: 1 }}
          exit={{ width: '100%', opacity: 0, transition: { duration: reduced ? 0 : 0.6, delay: reduced ? 0 : 0.6 } }}
          transition={{ duration: reduced ? 0 : 0.6, ease: [0.22, 1, 0.36, 1] }}
        />
      )}
    </AnimatePresence>
  )
}
