import { Link } from 'react-router-dom'
import { CATEGORY_LABELS, VERIFICATION_LABELS, dateSentence, t, type Lang } from '../i18n'
import { formatSeconds } from '../lib/format'
import { MOSAIC_QIDS, exampleByQid, type ExampleUniversity } from '../data/examples'
import Icon from './Icon'

function ExampleCard({ example, lang, wide }: { example: ExampleUniversity; lang: Lang; wide?: boolean }) {
  const { photo } = example
  return (
    <Link
      to={`/u/${example.qid}`}
      className={`card card-hover overflow-hidden block group ${wide ? 'col-span-2' : ''}`}
      aria-label={`${t(lang, 'home_preview_open')}: ${lang === 'ru' ? example.name_ru : example.name}`}
    >
      <div className={`relative overflow-hidden bg-paper-2 ${wide ? 'aspect-[16/9]' : 'aspect-[4/3]'}`}>
        <img
          src={photo.thumb}
          alt={photo.title}
          width={photo.width}
          height={photo.height}
          loading="eager"
          decoding="async"
          className="block w-full h-full object-cover transition-transform duration-700 ease-out group-hover:scale-[1.04]"
        />
        <div className="absolute inset-x-0 top-0 p-3 flex items-start justify-between gap-2">
          <span className="badge badge-frost">{CATEGORY_LABELS[photo.category][lang]}</span>
          <span className="badge badge-verified">
            <Icon name="check" size={12} strokeWidth={2.75} />
            {VERIFICATION_LABELS.verified[lang]}
          </span>
        </div>
      </div>
      <div className={`p-3.5 md:p-4 ${wide ? 'md:flex md:items-end md:justify-between md:gap-6' : ''}`}>
        <p className={`font-serif leading-[1.15] m-0 ${wide ? 'text-[20px] md:text-[24px]' : 'text-[17px] md:text-[18px]'}`}>
          {lang === 'ru' ? example.name_ru : example.name}
        </p>
        <p className="mt-1.5 md:mt-1 text-[12.5px] text-ink-3 m-0 flex items-center gap-1.5 flex-wrap">
          <Icon name="link" size={12} />
          <span>
            {photo.source_label}, {dateSentence(photo, lang)}
          </span>
        </p>
      </div>
    </Link>
  )
}

/** The hero's right column: three real cards from finished profiles plus a floating run card
 *  with the numbers of the run they were captured from. */
export default function PreviewMosaic({ lang }: { lang: Lang }) {
  const examples = MOSAIC_QIDS.map(exampleByQid).filter((e): e is ExampleUniversity => !!e)
  const lead = examples[0]
  return (
    <div className="relative">
      <p className="eyebrow m-0 mb-3 flex items-center gap-2">
        <span className="w-[6px] h-[6px] rounded-full bg-accent" aria-hidden="true" />
        {t(lang, 'home_preview_label')}
      </p>
      <div className="grid grid-cols-2 gap-3 md:gap-4">
        {examples.map((example, i) => (
          <ExampleCard key={example.qid} example={example} lang={lang} wide={i === 0} />
        ))}
      </div>
      {lead && (
        <div className="card rounded-[12px] shadow-lift px-4 py-3 mt-4 md:mt-0 md:absolute md:-bottom-6 md:-left-8 flex items-center gap-3 max-w-[320px]">
          <span className="vdot vdot-verified w-8 h-8" aria-hidden="true">
            <Icon name="check" size={14} strokeWidth={2.75} />
          </span>
          <div className="min-w-0">
            <p className="text-[13.5px] font-medium leading-tight m-0">
              {t(lang, 'home_stat_line', { verified: lead.run.verified, shown: lead.run.shown })}
            </p>
            <p className="text-[12px] text-ink-3 leading-tight mt-1 m-0 truncate">
              {t(lang, 'home_stat_sub', {
                name: lang === 'ru' ? 'MIT' : 'MIT',
                seconds: formatSeconds(lead.run.total_ms, lang),
              })}
            </p>
          </div>
        </div>
      )}
      <p className="mt-6 md:mt-10 text-[13px] leading-[1.6] text-ink-3 max-w-[48ch] m-0">
        {t(lang, 'home_preview_note')}
      </p>
    </div>
  )
}
