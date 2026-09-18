/** ErrorState — fatal error */
import type { Lang } from '../i18n'
import { UI } from '../i18n'

interface Props {
  error: string
  lang: Lang
  onRetry: () => void
}

export default function ErrorState({ error, lang, onRetry }: Props) {
  const t = (k: string) => UI[k]?.[lang] ?? k

  return (
    <div className="flex flex-col items-center justify-center py-20 text-center px-4">
      <div className="w-16 h-16 bg-red-100 text-red-600 rounded-full flex items-center justify-center text-3xl mb-4">
        ✕
      </div>
      <h2 className="text-xl font-bold text-slate-900 mb-2">Ошибка</h2>
      <p className="text-slate-600 max-w-md mb-6">{error}</p>
      <button 
        onClick={onRetry}
        className="px-6 py-2.5 bg-blue-600 text-white font-medium rounded-xl hover:bg-blue-700 transition shadow-sm"
      >
        {t('retryButton')}
      </button>
    </div>
  )
}
