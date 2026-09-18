/** EmptyState — when a category has no photos */
import type { Lang } from '../i18n'
import { UI } from '../i18n'

export default function EmptyState({ lang }: { lang: Lang }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-slate-500 bg-slate-50 rounded-2xl border border-dashed border-slate-200">
      <div className="text-4xl mb-4 opacity-50">📷</div>
      <p>{UI.noPhotosInCategory?.[lang] ?? UI.noPhotosInCategory.ru}</p>
    </div>
  )
}
