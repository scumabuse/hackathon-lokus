import { Link } from 'react-router-dom'
import { t, type Lang } from '../i18n'
import Icon from './Icon'
import LangSwitch from './LangSwitch'

interface Props {
  lang: Lang
  onToggleLang: () => void
  variant: 'home' | 'profile'
}

/** The site header: wordmark, section links on the landing page, a back link on profiles,
 *  the language control. 64 px tall on phones, 80 px from md up. */
export default function TopBar({ lang, onToggleLang, variant }: Props) {
  return (
    <header className="container-x">
      <div className="flex items-center justify-between gap-4 h-16 md:h-20">
        <div className="flex items-center gap-3 md:gap-6 min-w-0">
          {variant === 'profile' && (
            <Link to="/" className="btn btn-ghost btn-sm -ml-3 flex-none">
              <Icon name="arrow-left" size={16} />
              <span className="hidden sm:inline">{t(lang, 'topbar_back')}</span>
            </Link>
          )}
          <Link
            to="/"
            aria-label={t(lang, 'topbar_home_aria')}
            className="font-serif text-[22px] md:text-[24px] leading-none tracking-[-0.01em] whitespace-nowrap"
          >
            Visual <em className="not-italic md:italic">Campus</em>
          </Link>
        </div>
        <nav className="flex items-center gap-1 md:gap-3">
          {variant === 'home' && (
            <>
              <a href="#how" className="btn btn-ghost btn-sm hidden md:inline-flex">
                {t(lang, 'topbar_how')}
              </a>
              <a href="#sources" className="btn btn-ghost btn-sm hidden md:inline-flex">
                {t(lang, 'topbar_sources')}
              </a>
            </>
          )}
          <LangSwitch lang={lang} onToggle={onToggleLang} />
        </nav>
      </div>
    </header>
  )
}
