import type { Description } from '../types'
import { BASIS_SENTENCES, t, type Lang } from '../i18n'

/** The description as a serif reading column (≤ 62 ch) with its source links and basis. */
export default function Lead({ description, lang }: { description: Description; lang: Lang }) {
  const text = lang === 'ru' ? description.text_ru : description.text_en
  return (
    <div>
      <p className="font-serif text-[20px] md:text-[23px] leading-[1.5] max-w-[62ch] text-ink m-0">
        {text}
      </p>
      <p className="mt-4 text-[13px] leading-[1.6] text-ink-3 max-w-[62ch] m-0">
        {description.sources.length > 0 && (
          <>
            {t(lang, 'description_sources')}
            {description.sources.map((s, i) => (
              <span key={s.url}>
                <a href={s.url} target="_blank" rel="noopener noreferrer" className="link text-ink-2">
                  {s.title}
                </a>
                {i < description.sources.length - 1 ? ', ' : '. '}
              </span>
            ))}
          </>
        )}
        {BASIS_SENTENCES[description.basis][lang]}
      </p>
    </div>
  )
}
