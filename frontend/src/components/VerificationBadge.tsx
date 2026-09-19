import { forwardRef } from 'react'
import type { Verification } from '../types'
import { VERIFICATION_LABELS, t, type Lang } from '../i18n'
import Icon from './Icon'

interface Props {
  verification: Verification
  lang: Lang
  expanded: boolean
  controls: string
  onClick: () => void
  className?: string
}

/** The verification pill: terracotta with a check for «Подтверждено», white outline for
 *  «Вероятно», dashed for «Не подтверждено». A button that opens the reasons popover. */
const VerificationBadge = forwardRef<HTMLButtonElement, Props>(function VerificationBadge(
  { verification, lang, expanded, controls, onClick, className = '' },
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
      data-role="verification"
      className={`badge badge-${verification} cursor-pointer transition-transform hover:scale-[1.04] ${className}`}
    >
      {verification === 'verified' ? (
        <Icon name="check" size={12} strokeWidth={2.75} />
      ) : verification === 'likely' ? (
        <span className="w-[7px] h-[7px] rounded-full border-[1.5px] border-current" aria-hidden="true" />
      ) : (
        <Icon name="minus" size={12} strokeWidth={2.5} />
      )}
      {label}
    </button>
  )
})

export default VerificationBadge
