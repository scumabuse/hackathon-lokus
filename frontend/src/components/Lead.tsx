import type { Description } from '../types'
import { BASIS_SENTENCES, t, type Lang } from '../i18n'

/** The description as the serif lead paragraph + caption links + basis sentence (B5.5). */
export default function Lead({ description, lang }: { description: Description; lang: Lang }) {
  const text = lang === 'ru' ? description.text_ru : description.text_en
  return (
    <section className="mt-8">
      <p className="font-serif text-[26px] leading-[1.3] max-w-[60ch]">{text}</p>
      <p className="mt-3 text-[13px] text-ink-2 max-w-[60ch]">
        {description.sources.length > 0 && (
          <>
            {t(lang, 'description_sources')}
            {description.sources.map((s, i) => (
              <span key={s.url}>
                <a href={s.url} target="_blank" rel="noopener noreferrer">
                  {s.title}
                </a>
                {i < description.sources.length - 1 ? ', ' : '. '}
              </span>
            ))}
          </>
        )}
        {BASIS_SENTENCES[description.basis][lang]}
      </p>
    </section>
  )
}
