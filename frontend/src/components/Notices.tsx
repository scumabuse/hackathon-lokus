import type { Warning } from '../types'
import { noticeSentence, type Lang } from '../i18n'

/** ONE surface block with plain sentences, no icons, no borders (B5.4). */
export default function Notices({ warnings, lang }: { warnings: Warning[]; lang: Lang }) {
  const sentences: string[] = []
  for (const warning of warnings) {
    const sentence = noticeSentence(warning, lang)
    if (sentence && !sentences.includes(sentence)) sentences.push(sentence)
  }
  if (sentences.length === 0) return null
  return (
    <div className="mt-6 bg-surface p-4 max-w-[80ch]" role="status">
      {sentences.map((s) => (
        <p key={s} className="text-[15px] leading-[1.5]">
          {s}
        </p>
      ))}
    </div>
  )
}
