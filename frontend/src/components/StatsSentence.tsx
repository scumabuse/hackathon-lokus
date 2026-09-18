import type { Stats } from '../types'
import { t, type Lang } from '../i18n'
import { plural } from '../lib/format'

/** «Нашли 123 снимка, убрали 21 дубль и 9 нерелевантных, показываем 33.» (B5.6) */
export default function StatsSentence({ stats, lang }: { stats: Stats; lang: Lang }) {
  const sentence = t(lang, 'stats_sentence', {
    found: stats.found,
    found_word: plural(stats.found, lang === 'ru' ? ['снимок', 'снимка', 'снимков'] : ['picture', 'pictures', 'pictures'], lang),
    dupes: stats.duplicates_removed,
    dupes_word: plural(stats.duplicates_removed, lang === 'ru' ? ['дубль', 'дубля', 'дублей'] : ['duplicate', 'duplicates', 'duplicates'], lang),
    irrel: stats.irrelevant_removed,
    irrel_word: plural(stats.irrelevant_removed, lang === 'ru' ? ['нерелевантный', 'нерелевантных', 'нерелевантных'] : ['irrelevant one', 'irrelevant ones', 'irrelevant ones'], lang),
    shown: stats.shown,
  })
  return <p className="mt-6 text-[15px] max-w-[80ch]">{sentence}</p>
}
