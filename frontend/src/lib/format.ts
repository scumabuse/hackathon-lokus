/** Russian/English number, date and plural formatting (FIX_AND_RESTYLE B8). */

import type { Lang } from '../i18n'

const THIN_SPACE = ' '

const RU_MONTHS_GENITIVE = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]
const EN_MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

/** 18.4 -> "18,4" (ru) / "18.4" (en); integers stay integers. */
export function formatNumber(value: number, lang: Lang, fractionDigits = 1): string {
  const fixed = Number.isInteger(value) ? String(value) : value.toFixed(fractionDigits)
  return lang === 'ru' ? fixed.replace('.', ',') : fixed
}

/** Milliseconds -> "18,4 с" / "18.4 s" with a thin space before the unit. */
export function formatSeconds(ms: number, lang: Lang): string {
  const unit = lang === 'ru' ? 'с' : 's'
  return `${formatNumber(Math.max(0, ms) / 1000, lang, 1)}${THIN_SPACE}${unit}`
}

/** Kilometres -> "4,2 км" / "4.2 km". */
export function formatKm(km: number, lang: Lang): string {
  const unit = lang === 'ru' ? 'км' : 'km'
  return `${formatNumber(km, lang, 1)}${THIN_SPACE}${unit}`
}

/** Metres -> "210 м" below 1 km, else "1,2 км". */
export function formatDistance(meters: number, lang: Lang): string {
  if (meters < 1000) {
    const unit = lang === 'ru' ? 'м' : 'm'
    return `${Math.round(meters)}${THIN_SPACE}${unit}`
  }
  return formatKm(meters / 1000, lang)
}

/** "2019-05-04" -> "4 мая 2019" / "4 May 2019"; anything unparseable is returned as is. */
export function formatDate(isoDate: string, lang: Lang): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate)
  if (!match) return isoDate
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (month < 1 || month > 12) return isoDate
  const months = lang === 'ru' ? RU_MONTHS_GENITIVE : EN_MONTHS
  return `${day} ${months[month - 1]} ${year}`
}

/** 0.9 -> "0,90" / "0.90". */
export function formatConfidence(value: number, lang: Lang): string {
  const fixed = value.toFixed(2)
  return lang === 'ru' ? fixed.replace('.', ',') : fixed
}

/** Russian plural: forms = [1, 2-4, 5-20]; English: [singular, plural, plural]. */
export function plural(n: number, forms: [string, string, string], lang: Lang): string {
  if (lang !== 'ru') return n === 1 ? forms[0] : forms[1]
  const abs = Math.abs(n) % 100
  const last = abs % 10
  if (abs > 10 && abs < 20) return forms[2]
  if (last > 1 && last < 5) return forms[1]
  if (last === 1) return forms[0]
  return forms[2]
}

/** "N minutes ago" for the cached line: «5 минут назад», «только что», «2 часа назад». */
export function formatAgo(isoTimestamp: string, lang: Lang, now: Date = new Date()): string {
  const then = new Date(isoTimestamp)
  const minutes = Math.max(0, Math.round((now.getTime() - then.getTime()) / 60000))
  if (Number.isNaN(minutes)) return ''
  if (minutes < 1) return lang === 'ru' ? 'только что' : 'just now'
  if (minutes < 60) {
    return lang === 'ru'
      ? `${minutes} ${plural(minutes, ['минуту', 'минуты', 'минут'], lang)} назад`
      : `${minutes} ${plural(minutes, ['minute', 'minutes', 'minutes'], lang)} ago`
  }
  const hours = Math.round(minutes / 60)
  return lang === 'ru'
    ? `${hours} ${plural(hours, ['час', 'часа', 'часов'], lang)} назад`
    : `${hours} ${plural(hours, ['hour', 'hours', 'hours'], lang)} ago`
}

/** Fill {placeholders} in an i18n template. */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) =>
    key in values ? String(values[key]) : whole,
  )
}
