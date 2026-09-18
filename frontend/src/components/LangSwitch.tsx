import { t, type Lang } from '../i18n'

/** Language toggle as an underlined text link (no pills, no icons). */
export default function LangSwitch({ lang, onToggle }: { lang: Lang; onToggle: () => void }) {
  return (
    <button
      type="button"
      className="textlink text-[13px] text-ink-2"
      onClick={onToggle}
      aria-label={t(lang, 'lang_switch_aria')}
      lang={lang === 'ru' ? 'en' : 'ru'}
    >
      {t(lang, 'lang_switch')}
    </button>
  )
}
