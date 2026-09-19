import type { Warning } from '../types'
import { noticeSentence, type Lang } from '../i18n'
import Icon from './Icon'

/** Plain-sentence callouts for the pipeline warnings (one per distinct sentence). */
export default function Notices({ warnings, lang }: { warnings: Warning[]; lang: Lang }) {
  const sentences: string[] = []
  for (const warning of warnings) {
    const sentence = noticeSentence(warning, lang)
    if (sentence && !sentences.includes(sentence)) sentences.push(sentence)
  }
  if (sentences.length === 0) return null
  return (
    <div className="grid gap-2" role="status">
      {sentences.map((s) => (
        <div key={s} className="notice">
          <span className="text-ink-3 mt-[3px] flex-none">
            <Icon name="info" size={16} />
          </span>
          <p className="text-[14px] leading-[1.55] text-ink-2 m-0">{s}</p>
        </div>
      ))}
    </div>
  )
}
