import { LANGS, t, type Lang } from '../i18n'

/** Segmented RU | EN control; the inactive segment switches the language. */
export default function LangSwitch({ lang, onToggle }: { lang: Lang; onToggle: () => void }) {
  return (
    <div className="seg" role="group" aria-label={t(lang, 'lang_switch_aria')}>
      {LANGS.map((code) => (
        <button
          key={code}
          type="button"
          aria-pressed={lang === code}
          lang={code}
          onClick={() => {
            if (lang !== code) onToggle()
          }}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  )
}
