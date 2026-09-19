import { Link } from 'react-router-dom'
import { t, type Lang } from '../i18n'
import { EXAMPLES } from '../data/examples'
import Icon from './Icon'

/** «Попробуйте на примере»: six clickable university cards with a real cover each. */
export default function UniversityCards({ lang }: { lang: Lang }) {
  return (
    <section className="mt-20 md:mt-28">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-[640px]">
          <p className="eyebrow m-0">{t(lang, 'home_examples')}</p>
          <h2 className="display text-[34px] md:text-[44px] mt-3 m-0">{t(lang, 'examples_title')}</h2>
          <p className="mt-3 text-[16px] md:text-[17px] text-ink-2 m-0">{t(lang, 'examples_sub')}</p>
        </div>
      </div>
      <ul className="m-0 mt-8 md:mt-10 p-0 list-none grid gap-4 md:gap-5 grid-cols-2 md:grid-cols-3 hd:grid-cols-6">
        {EXAMPLES.map((u) => (
          <li key={u.qid}>
            <Link
              to={`/u/${u.qid}`}
              className="card card-hover overflow-hidden block group h-full"
              aria-label={`${t(lang, 'examples_open')}: ${lang === 'ru' ? u.name_ru : u.name}`}
            >
              <div className="relative aspect-[4/3] overflow-hidden bg-paper-2">
                <img
                  src={u.photo.thumb}
                  alt={u.photo.title}
                  loading="lazy"
                  decoding="async"
                  className="block w-full h-full object-cover transition-transform duration-700 ease-out group-hover:scale-[1.05]"
                />
              </div>
              <div className="p-3.5 md:p-4">
                <p className="font-serif text-[17px] leading-[1.2] m-0">{lang === 'ru' ? u.name_ru : u.name}</p>
                <p className="mt-2 text-[12.5px] text-ink-3 m-0 flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1 min-w-0">
                    <Icon name="pin" size={12} />
                    <span className="truncate">
                      {u.city}, {u.country}
                    </span>
                  </span>
                  <span className="text-ink-2 transition-transform group-hover:translate-x-0.5" aria-hidden="true">
                    <Icon name="arrow-right" size={14} />
                  </span>
                </p>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
