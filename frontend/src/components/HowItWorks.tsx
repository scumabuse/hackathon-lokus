import { t, type Lang } from '../i18n'
import Icon, { type IconName } from './Icon'

const STEPS: Array<{ n: string; icon: IconName; title: string; text: string }> = [
  { n: '01', icon: 'search', title: 'how_1_title', text: 'how_1_text' },
  { n: '02', icon: 'check', title: 'how_2_title', text: 'how_2_text' },
  { n: '03', icon: 'image', title: 'how_3_title', text: 'how_3_text' },
]

/** «Как это работает»: three numbered cards on a warm band. */
export default function HowItWorks({ lang }: { lang: Lang }) {
  return (
    <section id="how" className="scroll-mt-20 mt-20 md:mt-28">
      <div className="max-w-[640px]">
        <p className="eyebrow m-0">{t(lang, 'topbar_how')}</p>
        <h2 className="display text-[34px] md:text-[44px] mt-3 m-0">{t(lang, 'how_title')}</h2>
        <p className="mt-3 text-[16px] md:text-[17px] text-ink-2 m-0">{t(lang, 'how_sub')}</p>
      </div>
      <ol className="m-0 mt-8 md:mt-10 p-0 list-none grid gap-4 md:gap-5 md:grid-cols-3">
        {STEPS.map((step) => (
          <li key={step.n} className="card card-hover rounded-xl p-6 md:p-7 flex flex-col">
            <div className="flex items-center justify-between">
              <span className="font-serif italic text-[36px] leading-none text-accent" aria-hidden="true">
                {step.n}
              </span>
              <span className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-paper-2 text-ink">
                <Icon name={step.icon} size={18} />
              </span>
            </div>
            <h3 className="mt-6 text-[18px] font-semibold leading-tight m-0">{t(lang, step.title)}</h3>
            <p className="mt-2 text-[15px] leading-[1.55] text-ink-2 m-0">{t(lang, step.text)}</p>
          </li>
        ))}
      </ol>
    </section>
  )
}
