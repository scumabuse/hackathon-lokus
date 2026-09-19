import { Link } from 'react-router-dom'
import { t, type Lang } from '../i18n'
import Icon from './Icon'

/** «Не удалось загрузить профиль: {message}.» with a retry button and the way home. */
export default function ErrorState({
  message,
  lang,
  onRetry,
}: {
  message: string
  lang: Lang
  onRetry: () => void
}) {
  return (
    <div className="card rounded-xl p-8 md:p-12 mt-10 max-w-[640px] text-center" role="alert">
      <span className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-accent-soft text-accent">
        <Icon name="info" size={22} />
      </span>
      <p className="mt-5 text-[17px] leading-[1.5] m-0">{t(lang, 'error_title', { message })}</p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <button type="button" className="btn" onClick={onRetry}>
          <Icon name="refresh" size={15} />
          {t(lang, 'error_retry')}
        </button>
        <Link to="/" className="btn btn-secondary">
          {t(lang, 'topbar_back')}
        </Link>
      </div>
    </div>
  )
}
