import { Link } from 'react-router-dom'
import { t, type Lang } from '../i18n'
import LangSwitch from './LangSwitch'

const SOURCE_KEYS = ['sources_wikidata', 'sources_commons', 'sources_wikipedia', 'sources_official']

/** Shared footer: wordmark, the licence line, source chips, language control. */
export default function SiteFooter({ lang, onToggleLang }: { lang: Lang; onToggleLang: () => void }) {
  return (
    <footer className="mt-24 border-t border-line bg-paper-2/60">
      <div className="container-x py-10 md:py-12 grid gap-8 md:grid-cols-[1fr_auto] md:items-start">
        <div>
          <Link to="/" className="font-serif text-[22px] leading-none">
            Visual <em>Campus</em>
          </Link>
          <p className="mt-3 text-[14px] leading-[1.6] text-ink-2 max-w-[60ch]">{t(lang, 'footer_line')}</p>
          <ul className="mt-5 flex flex-wrap gap-2" aria-label={t(lang, 'topbar_sources')}>
            {SOURCE_KEYS.map((key) => (
              <li key={key} className="badge badge-soft h-8 px-3 text-[13px] font-medium">
                {t(lang, key)}
              </li>
            ))}
          </ul>
        </div>
        <div className="flex items-center gap-4 md:justify-end">
          <LangSwitch lang={lang} onToggle={onToggleLang} />
        </div>
      </div>
    </footer>
  )
}
