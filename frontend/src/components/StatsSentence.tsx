import type { Stats } from '../types'
import { t, type Lang } from '../i18n'
import { plural } from '../lib/format'

/** «Нашли 123 снимка, убрали 21 дубль и 9 нерелевантных, показываем 33.» as the grid title. */
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
  return (
    <h2 className="font-serif text-[24px] md:text-[30px] leading-[1.2] mt-2 m-0 max-w-[40ch] text-balance">
      {sentence}
    </h2>
  )
}
