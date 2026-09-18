/** i18n: Russian by default, English mirror. Every user-visible string, reason and warning
 *  code goes through this module; internal enum names are never shown (B5.4). */

import type {
  Category,
  DescriptionBasis,
  Photo,
  ReasonCode,
  Verification,
  Warning,
} from './types'
import { fill, formatDate, formatDistance } from './lib/format'

export type Lang = 'ru' | 'en'
type Str = Record<Lang, string>

export const LANGS: Lang[] = ['ru', 'en']

export const CATEGORY_LABELS: Record<Category, Str> = {
  campus: { ru: 'Кампус', en: 'Campus' },
  dormitory: { ru: 'Общежития', en: 'Dormitories' },
  classroom: { ru: 'Аудитории', en: 'Classrooms' },
  library: { ru: 'Библиотеки', en: 'Libraries' },
  lab: { ru: 'Лаборатории', en: 'Laboratories' },
  sport: { ru: 'Спорт', en: 'Sport' },
  student_life: { ru: 'Студенческая жизнь', en: 'Student life' },
  city: { ru: 'Город', en: 'City' },
  other: { ru: 'Прочее', en: 'Other' },
}

/** The tab order of the nav row (B5.7). */
export const NAV_CATEGORIES: Category[] = [
  'campus',
  'dormitory',
  'classroom',
  'library',
  'lab',
  'sport',
  'student_life',
  'city',
]

export const VERIFICATION_LABELS: Record<Verification, Str> = {
  verified: { ru: 'Подтверждено', en: 'Verified' },
  likely: { ru: 'Вероятно', en: 'Likely' },
  unverified: { ru: 'Не подтверждено', en: 'Unverified' },
}

export const REASON_SENTENCES: Record<ReasonCode, Str> = {
  wikidata_main_image: {
    ru: 'Это главное фото университета в Wikidata.',
    en: 'This is the main image of the university on Wikidata.',
  },
  official_site_source: {
    ru: 'Снимок взят с официального сайта университета.',
    en: 'The photo comes from the official university website.',
  },
  commons_category_source: {
    ru: 'Фото из категории университета на Wikimedia Commons.',
    en: 'The photo is filed in the university category on Wikimedia Commons.',
  },
  commons_search_source: {
    ru: 'Фото найдено поиском по Wikimedia Commons, сама категория его не подтверждает.',
    en: 'The photo was found by searching Wikimedia Commons; the category does not vouch for it.',
  },
  commons_geo_source: {
    ru: 'Фото с геометкой на Wikimedia Commons рядом с кампусом.',
    en: 'A geotagged Wikimedia Commons photo near the campus.',
  },
  flickr_geo_source: {
    ru: 'Фото с геометкой на Flickr рядом с кампусом.',
    en: 'A geotagged Flickr photo near the campus.',
  },
  web_search_source: {
    ru: 'Найдено веб-поиском, источник не подтверждён.',
    en: 'Found by web search; the source is unverified.',
  },
  city_category_source: {
    ru: 'Фото города из категории города на Wikimedia Commons.',
    en: 'A city photo from the city category on Wikimedia Commons.',
  },
  name_in_metadata: {
    ru: 'Название университета есть в подписи, описании или имени файла.',
    en: 'The university name appears in the caption, description or file name.',
  },
  name_on_sign: {
    ru: 'Название университета читается на вывеске в кадре.',
    en: 'The university name is readable on a sign in the picture.',
  },
  geo_within_300m: {
    ru: 'Геометка в 300 м от кампуса.',
    en: 'Geotagged within 300 m of the campus.',
  },
  geo_within_1km: {
    ru: 'Геометка в километре от кампуса.',
    en: 'Geotagged within 1 km of the campus.',
  },
  vision_consistent: {
    ru: 'Визуальная проверка: сцена соответствует категории.',
    en: 'Visual check: the scene matches the category.',
  },
  vision_unavailable: {
    ru: 'Визуальная проверка была недоступна, поэтому выше «вероятно» оценка не поднимается.',
    en: 'The visual check was unavailable, so the label cannot rise above “likely”.',
  },
  vision_timeout: {
    ru: 'Визуальная проверка не успела за отведённое время, поэтому оценка не выше «вероятно».',
    en: 'The visual check did not finish in time, so the label cannot rise above “likely”.',
  },
  category_heuristic: {
    ru: 'Категория определена по ключевым словам в названии, а не по снимку.',
    en: 'The category was chosen from keywords in the title, not from the image.',
  },
  cached_result: {
    ru: 'Результат взят из кэша.',
    en: 'The result comes from the cache.',
  },
}

export const BASIS_SENTENCES: Record<DescriptionBasis, Str> = {
  wikipedia_and_site: {
    ru: 'Описание построено по Wikipedia и официальному сайту.',
    en: 'The description is based on Wikipedia and the official site.',
  },
  wikipedia_only: {
    ru: 'Описание построено только по Wikipedia.',
    en: 'The description is based on Wikipedia only.',
  },
  site_only: {
    ru: 'Описание построено только по официальному сайту.',
    en: 'The description is based on the official site only.',
  },
  insufficient: {
    ru: 'Открытых данных для описания кампуса недостаточно.',
    en: 'There is not enough open data to describe the campus.',
  },
}

export const UI: Record<string, Str> = {
  app_name: { ru: 'Visual Campus', en: 'Visual Campus' },
  lang_switch: { ru: 'English', en: 'Русский' },
  lang_switch_aria: { ru: 'Switch to English', en: 'Переключить на русский' },

  home_headline: {
    ru: 'Университет — таким, каким его увидит студент.',
    en: 'A university the way a student will see it.',
  },
  home_input_label: { ru: 'Название университета', en: 'University name' },
  home_button: { ru: 'Собрать профиль', en: 'Build the profile' },
  home_promise: {
    ru: 'Введите название — за 30 секунд мы соберём из открытых источников фотографии кампуса, общежитий, аудиторий, библиотек, лабораторий, спорта и студенческой жизни, проверим, что каждая относится именно к этому университету, и покажем только подтверждённые снимки со ссылкой на источник.',
    en: 'Type a name and within 30 seconds we gather photos of the campus, dormitories, classrooms, libraries, laboratories, sport and student life from open sources, verify that each one belongs to this university and show only confirmed pictures with a link to their source.',
  },
  home_examples: { ru: 'Например:', en: 'For example:' },
  home_footer: {
    ru: 'Источники: Wikimedia Commons, Wikipedia, официальные сайты университетов. Для небольших вузов данных может быть мало — сервис скажет об этом прямо.',
    en: 'Sources: Wikimedia Commons, Wikipedia, official university websites. Small universities may have little data; the service says so plainly.',
  },
  home_searching: { ru: 'Ищем', en: 'Searching' },
  home_not_found: {
    ru: 'Университет не найден. Проверьте написание или введите официальное английское название.',
    en: 'University not found. Check the spelling or enter the official English name.',
  },
  home_corrected: {
    ru: 'Показаны результаты по исправленному названию: {name}.',
    en: 'Results are shown for the corrected name: {name}.',
  },
  home_several: {
    ru: 'Нашлось несколько университетов, выберите нужный.',
    en: 'Several universities match, choose the one you mean.',
  },
  home_error: {
    ru: 'Не удалось выполнить поиск: {message}. Попробуйте ещё раз.',
    en: 'The search failed: {message}. Try again.',
  },

  status_connecting: { ru: 'Открываем профиль', en: 'Opening the profile' },
  status_searching: {
    ru: 'Ищем фотографии в Wikimedia Commons и на официальном сайте',
    en: 'Looking for photos on Wikimedia Commons and the official site',
  },
  status_verifying: {
    ru: 'Проверяем, что снимки относятся к университету',
    en: 'Checking that the pictures belong to the university',
  },
  status_sorting: {
    ru: 'Раскладываем по категориям и убираем дубли',
    en: 'Sorting into categories and removing duplicates',
  },
  status_done: { ru: 'Профиль готов за {seconds}', en: 'Profile ready in {seconds}' },
  status_cached: {
    ru: 'Профиль собран {ago} и показан из кэша',
    en: 'Profile built {ago}, served from the cache',
  },
  progress_aria: { ru: 'Ход сборки профиля', en: 'Profile build progress' },

  masthead_place: { ru: '{city}, {country}.', en: '{city}, {country}.' },
  masthead_distance: {
    ru: 'Кампус в {km} от центра города.',
    en: 'The campus is {km} from the city centre.',
  },
  masthead_site: { ru: 'Официальный сайт', en: 'Official site' },
  masthead_wikipedia: { ru: 'Wikipedia', en: 'Wikipedia' },
  masthead_cached: { ru: 'Собрано {ago}.', en: 'Built {ago}.' },
  masthead_refresh: { ru: 'Обновить', en: 'Refresh' },
  masthead_back: { ru: 'Другой университет', en: 'Another university' },

  notice_low_data: {
    ru: 'Проверенных фотографий этого университета в открытых источниках мало. Показываем только то, что удалось подтвердить.',
    en: 'Open sources hold few verified photos of this university. We show only what we could confirm.',
  },
  notice_source_unavailable: {
    ru: 'Источник {name} сейчас недоступен, профиль собран без него.',
    en: 'The source {name} is unavailable right now; the profile was built without it.',
  },
  notice_no_coordinates: {
    ru: 'Координаты кампуса не указаны в открытых данных, карта и расстояния недоступны.',
    en: 'Open data has no campus coordinates, so the map and distances are unavailable.',
  },
  notice_no_commons_category: {
    ru: 'У университета нет своей категории на Wikimedia Commons, фотографий может быть меньше.',
    en: 'The university has no category of its own on Wikimedia Commons, so there may be fewer photos.',
  },
  notice_no_official_site: {
    ru: 'Официальный сайт не указан в открытых данных.',
    en: 'Open data lists no official website.',
  },
  notice_vision_unavailable: {
    ru: 'Визуальная проверка сейчас недоступна, поэтому снимки помечены не выше чем «вероятно».',
    en: 'The visual check is unavailable right now, so no picture is labelled above “likely”.',
  },
  notice_time_budget: {
    ru: 'Не всё успело завершиться за отведённые 30 секунд ({stage}); такие снимки помечены как непроверенные или показаны без части данных.',
    en: 'Not everything finished within the 30-second budget ({stage}); those pictures are marked unverified or shown with less data.',
  },
  stage_vision: { ru: 'этап проверки снимков', en: 'the verification stage' },
  stage_download: { ru: 'этап загрузки изображений', en: 'the download stage' },
  notice_queued: {
    ru: 'Сервис сейчас занят, запрос стоит в очереди и займёт чуть больше времени.',
    en: 'The service is busy; the request is queued and will take a little longer.',
  },
  notice_ambiguous: {
    ru: 'Название неоднозначно, возможно, имелся в виду другой университет.',
    en: 'The name is ambiguous; a different university may have been meant.',
  },

  description_sources: { ru: 'Источники: ', en: 'Sources: ' },

  stats_sentence: {
    ru: 'Нашли {found} {found_word}, убрали {dupes} {dupes_word} и {irrel} {irrel_word}, показываем {shown}.',
    en: 'Found {found} {found_word}, removed {dupes} {dupes_word} and {irrel} {irrel_word}, showing {shown}.',
  },

  nav_all: { ru: 'Все', en: 'All' },
  nav_show_unverified: { ru: 'Показать непроверенные ({n})', en: 'Show unverified ({n})' },
  nav_hide_unverified: { ru: 'Скрыть непроверенные ({n})', en: 'Hide unverified ({n})' },
  nav_aria: { ru: 'Категории фотографий', en: 'Photo categories' },
  empty_category: {
    ru: 'В открытых источниках не нашлось проверенных фото по категории «{label}».',
    en: 'Open sources hold no verified photos in the “{label}” category.',
  },
  empty_all: {
    ru: 'Проверенных фотографий пока нет.',
    en: 'No verified photos yet.',
  },
  skeleton_aria: { ru: 'Загружаем фотографии', en: 'Loading photos' },

  frame_taken: { ru: 'снято {date}', en: 'taken {date}' },
  frame_published: { ru: 'опубликовано {date}', en: 'published {date}' },
  frame_uploaded: { ru: 'загружено {date}', en: 'uploaded {date}' },
  frame_date_unknown: { ru: 'дата неизвестна', en: 'date unknown' },
  frame_distance: { ru: '{distance} от кампуса', en: '{distance} from the campus' },
  frame_open: { ru: 'Открыть снимок', en: 'Open the picture' },
  mark_aria: { ru: '{label}. Показать причины', en: '{label}. Show the reasons' },

  popover_title: { ru: '{label}, уверенность {confidence}', en: '{label}, confidence {confidence}' },
  popover_close: { ru: 'Закрыть', en: 'Close' },
  popover_aria: { ru: 'Причины оценки', en: 'Reasons for the label' },

  lightbox_aria: { ru: 'Просмотр снимка', en: 'Picture viewer' },
  lightbox_open_source: { ru: 'Открыть источник', en: 'Open the source' },
  lightbox_open_original: { ru: 'Открыть оригинал', en: 'Open the original' },
  lightbox_close: { ru: 'Закрыть', en: 'Close' },
  lightbox_prev: { ru: 'Предыдущий', en: 'Previous' },
  lightbox_next: { ru: 'Следующий', en: 'Next' },
  lightbox_counter: { ru: 'Снимок {i} из {n}', en: 'Picture {i} of {n}' },
  lightbox_category: { ru: 'Категория', en: 'Category' },
  lightbox_source: { ru: 'Источник', en: 'Source' },
  lightbox_author: { ru: 'Автор', en: 'Author' },
  lightbox_license: { ru: 'Лицензия', en: 'Licence' },
  lightbox_date: { ru: 'Дата', en: 'Date' },
  lightbox_distance: { ru: 'Расстояние до кампуса', en: 'Distance to the campus' },
  lightbox_confidence: { ru: 'Уверенность', en: 'Confidence' },
  lightbox_visible_text: { ru: 'Текст на снимке', en: 'Text in the picture' },
  lightbox_reasons: { ru: 'Почему мы так считаем', en: 'Why we think so' },

  map_caption: {
    ru: 'Красная точка — кампус, чёрная — центр города. Расстояние {km}.',
    en: 'The red dot is the campus, the black one the city centre. Distance {km}.',
  },
  map_aria: { ru: 'Карта: кампус и центр города', en: 'Map: campus and city centre' },

  error_title: {
    ru: 'Не удалось загрузить профиль: {message}.',
    en: 'The profile could not be loaded: {message}.',
  },
  error_retry: { ru: 'Попробовать снова', en: 'Try again' },
  error_network: { ru: 'нет связи с сервером', en: 'no connection to the server' },
}

export function t(lang: Lang, key: string, values?: Record<string, string | number>): string {
  const entry = UI[key]
  const text = entry ? entry[lang] : key
  return values ? fill(text, values) : text
}

/** Frame caption line 2 / lightbox date: «Wikimedia Commons, снято 4 мая 2019». */
export function dateSentence(photo: Photo, lang: Lang): string {
  if (photo.date) {
    const date = formatDate(photo.date, lang)
    if (photo.date_kind === 'published') return t(lang, 'frame_published', { date })
    if (photo.date_kind === 'uploaded') return t(lang, 'frame_uploaded', { date })
    return t(lang, 'frame_taken', { date })
  }
  return t(lang, 'frame_date_unknown')
}

export function distanceSentence(photo: Photo, lang: Lang): string | null {
  if (photo.distance_m == null) return null
  return t(lang, 'frame_distance', { distance: formatDistance(photo.distance_m, lang) })
}

/** The one notices block (B5.4): a plain sentence per warning, or null for warnings that are
 *  rendered elsewhere (missing_category = tab empty state, served_from_cache = masthead). */
export function noticeSentence(warning: Warning, lang: Lang): string | null {
  const detail = warning.detail ?? ''
  switch (warning.code) {
    case 'low_data':
      return t(lang, 'notice_low_data')
    case 'source_unavailable':
      return t(lang, 'notice_source_unavailable', { name: sourceName(detail, lang) })
    case 'no_coordinates':
      return t(lang, 'notice_no_coordinates')
    case 'no_commons_category':
      return t(lang, 'notice_no_commons_category')
    case 'no_official_site':
      return t(lang, 'notice_no_official_site')
    case 'vision_unavailable':
      return t(lang, 'notice_vision_unavailable')
    case 'time_budget_exceeded':
      return t(lang, 'notice_time_budget', {
        stage: detail.startsWith('download') ? t(lang, 'stage_download') : t(lang, 'stage_vision'),
      })
    case 'queued':
      return t(lang, 'notice_queued')
    case 'ambiguous_name':
      return t(lang, 'notice_ambiguous')
    default:
      return null
  }
}

/** Human names for source identifiers that arrive as warning details. */
export function sourceName(detail: string, lang: Lang): string {
  const names: Record<string, Str> = {
    official_site: { ru: 'официальный сайт', en: 'official site' },
    commons_category: { ru: 'категория Wikimedia Commons', en: 'Wikimedia Commons category' },
    commons_search: { ru: 'поиск Wikimedia Commons', en: 'Wikimedia Commons search' },
    commons_geo: { ru: 'геопоиск Wikimedia Commons', en: 'Wikimedia Commons geosearch' },
    city_commons: { ru: 'категория города на Wikimedia Commons', en: 'city category on Wikimedia Commons' },
    wikidata_p18: { ru: 'главное фото Wikidata', en: 'Wikidata main image' },
    flickr: { ru: 'Flickr', en: 'Flickr' },
    web_search: { ru: 'веб-поиск', en: 'web search' },
  }
  const key = detail.split(' ')[0]
  return names[key] ? names[key][lang] : detail
}
