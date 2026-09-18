import { forwardRef } from 'react'
import type { Verification } from '../types'
import { VERIFICATION_LABELS, t, type Lang } from '../i18n'

interface Props {
  verification: Verification
  lang: Lang
  expanded: boolean
  controls: string
  onClick: () => void
}

/** The editor's mark (B5.8): filled red = verified, black outline = likely, dashed = unverified.
 *  A 10 px dot with a 24 px hit area; opens the reasons popover. */
const Mark = forwardRef<HTMLButtonElement, Props>(function Mark(
  { verification, lang, expanded, controls, onClick },
  ref,
) {
  const label = VERIFICATION_LABELS[verification][lang]
  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      aria-label={t(lang, 'mark_aria', { label })}
      aria-expanded={expanded}
      aria-controls={controls}
      className="inline-flex items-center justify-center w-6 h-6 -m-[7px] mr-0 flex-none"
    >
      <span className={`mark mark-${verification}`} aria-hidden="true" />
    </button>
  )
})

export default Mark
