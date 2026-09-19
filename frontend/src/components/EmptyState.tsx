import { t, type Lang } from '../i18n'
import Icon from './Icon'

interface Props {
  lang: Lang
  categoryLabel: string | null
  hiddenCount: number
  showUnverified: boolean
  onShowAll: () => void
  onToggleUnverified: () => void
}

/** Honest empty state for a tab: the sentence, a hint and the one or two actions that help. */
export default function EmptyState({
  lang,
  categoryLabel,
  hiddenCount,
  showUnverified,
  onShowAll,
  onToggleUnverified,
}: Props) {
  return (
    <div className="rounded-lg border border-dashed border-line-2 bg-surface/60 px-6 py-12 md:py-16 text-center">
      <span className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-paper-2 text-ink-3">
        <Icon name="image" size={22} />
      </span>
      <p className="mt-4 text-[17px] font-medium max-w-[46ch] mx-auto m-0">
        {categoryLabel ? t(lang, 'empty_category', { label: categoryLabel }) : t(lang, 'empty_all')}
      </p>
      <p className="mt-2 text-[14px] text-ink-2 max-w-[46ch] mx-auto m-0">{t(lang, 'empty_hint')}</p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        {categoryLabel && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={onShowAll}>
            {t(lang, 'empty_all_button')}
          </button>
        )}
        {hiddenCount > 0 && !showUnverified && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={onToggleUnverified}>
            {t(lang, 'nav_show_unverified', { n: hiddenCount })}
          </button>
        )}
      </div>
    </div>
  )
}
