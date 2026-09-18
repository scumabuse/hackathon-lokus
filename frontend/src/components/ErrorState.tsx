import { t, type Lang } from '../i18n'

/** «Не удалось загрузить профиль: {message}.» + the one black button (B5.12). */
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
    <div className="mt-10 max-w-[60ch]" role="alert">
      <p className="text-[15px] leading-[1.5]">{t(lang, 'error_title', { message })}</p>
      <button type="button" className="btn mt-6" onClick={onRetry}>
        {t(lang, 'error_retry')}
      </button>
    </div>
  )
}
