/** i18n strings: ru (default) + en. Reason/warning code mappings included. */

import type { Category, ReasonCode, WarningCode } from './types'

export type Lang = 'ru' | 'en'

export const REASON_LABELS: Record<ReasonCode, Record<Lang, string>> = {
  wikidata_main_image: {
    ru: 'Главное фото университета из Wikidata',
    en: 'Main university image from Wikidata',
  },
  official_site_source: {
    ru: 'Фото с официального сайта университета',
    en: 'Photo from the official university website',
  },
  commons_category_source: {
    ru: 'Фото из категории университета на Wikimedia Commons',
    en: 'Photo from the university category on Wikimedia Commons',
  },
  commons_search_source: {
    ru: 'Фото найдено поиском на Wikimedia Commons',
    en: 'Photo found via Wikimedia Commons search',
  },
  commons_geo_source: {
    ru: 'Геолоцированное фото из Wikimedia Commons рядом с кампусом',
    en: 'Geotagged photo from Wikimedia Commons near campus',
  },
  flickr_geo_source: {
    ru: 'Геолоцированное фото из Flickr рядом с кампусом',
    en: 'Geotagged photo from Flickr near campus',
  },
  web_search_source: {
    ru: 'Найдено веб-поиском — источник не подтверждён',
    en: 'Found via web search — source unverified',
  },
  city_category_source: {
    ru: 'Фото города из категории города на Wikimedia Commons',
    en: 'City photo from the city category on Wikimedia Commons',
  },
  name_in_metadata: {
    ru: 'Название университета найдено в метаданных фото',
    en: 'University name found in photo metadata',
  },
  name_on_sign: {
    ru: 'Название университета читается на вывеске',
    en: 'University name readable on a sign',
  },
  geo_within_300m: {
    ru: 'Геометка в 300 м от кампуса',
    en: 'Geotagged within 300 m of campus',
  },
  geo_within_1km: {
    ru: 'Геометка в 1 км от кампуса',
    en: 'Geotagged within 1 km of campus',
  },
  vision_consistent: {
    ru: 'Визуальная проверка: сцена соответствует категории',
    en: 'Visual check: scene matches the category',
  },
  vision_unavailable: {
    ru: 'Визуальная проверка недоступна',
    en: 'Visual check unavailable',
  },
  vision_timeout: {
    ru: 'Визуальная проверка не завершилась в отведённое время',
    en: 'Visual check did not finish within the time budget',
  },
  category_heuristic: {
    ru: 'Категория определена по ключевым словам',
    en: 'Category determined by keywords',
  },
  cached_result: {
    ru: 'Результат из кэша',
    en: 'Cached result',
  },
}

export const WARNING_LABELS: Record<WarningCode, (detail?: string) => Record<Lang, string>> = {
  low_data: () => ({
    ru: 'Недостаточно проверенных фотографий для этого университета. Показываем только то, что удалось подтвердить.',
    en: 'Not enough verified photos for this university. Showing only what we could confirm.',
  }),
  no_coordinates: () => ({
    ru: 'Координаты университета не найдены в Wikidata.',
    en: 'University coordinates not found in Wikidata.',
  }),
  no_commons_category: () => ({
    ru: 'Категория Wikimedia Commons не указана в Wikidata.',
    en: 'Wikimedia Commons category not listed in Wikidata.',
  }),
  no_official_site: () => ({
    ru: 'Официальный сайт не указан в Wikidata.',
    en: 'Official website not listed in Wikidata.',
  }),
  source_unavailable: (detail) => ({
    ru: `Источник ${detail ?? ''} недоступен, профиль построен без него.`,
    en: `Source ${detail ?? ''} unavailable; profile built without it.`,
  }),
  vision_unavailable: (detail) => ({
    ru: `Визуальная проверка недоступна${detail ? ': ' + detail : ''}.`,
    en: `Visual verification unavailable${detail ? ': ' + detail : ''}.`,
  }),
  time_budget_exceeded: (detail) => ({
    ru: `Проверка части фото не завершилась в отведённые 30 секунд${detail ? ' (' + detail + ')' : ''}; такие фото помечены как непроверенные.`,
    en: `Part of the photo verification did not finish within 30 s${detail ? ' (' + detail + ')' : ''}; those photos are marked unverified.`,
  }),
  served_from_cache: (detail) => ({
    ru: `Результат из кэша${detail ? ', ' + detail : ''}.`,
    en: `Served from cache${detail ? ', ' + detail : ''}.`,
  }),
  ambiguous_name: () => ({
    ru: 'Имя неоднозначно — возможно несколько университетов.',
    en: 'Ambiguous name — multiple universities possible.',
  }),
  missing_category: (detail) => ({
    ru: `Не удалось найти проверенные фото категории «${detail ?? ''}».`,
    en: `No verified photos found for category "${detail ?? ''}".`,
  }),
  queued: () => ({
    ru: 'Запрос поставлен в очередь из-за высокой нагрузки.',
    en: 'Request queued due to high load.',
  }),
}

export const CATEGORY_LABELS: Record<Category, Record<Lang, string>> = {
  campus: { ru: 'Кампус', en: 'Campus' },
  dormitory: { ru: 'Общежития', en: 'Dormitories' },
  classroom: { ru: 'Аудитории', en: 'Classrooms' },
  library: { ru: 'Библиотеки', en: 'Libraries' },
  lab: { ru: 'Лаборатории', en: 'Labs' },
  sport: { ru: 'Спорт', en: 'Sport' },
  student_life: { ru: 'Студенческая жизнь', en: 'Student Life' },
  city: { ru: 'Город', en: 'City' },
  other: { ru: 'Прочее', en: 'Other' },
}

export const DATE_KIND_LABELS: Record<string, Record<Lang, string>> = {
  taken: { ru: 'Снято', en: 'Taken' },
  published: { ru: 'Опубликовано', en: 'Published' },
  uploaded: { ru: 'Загружено', en: 'Uploaded' },
  unknown: { ru: 'Дата неизвестна', en: 'Date unknown' },
}

export const VERIFICATION_LABELS: Record<string, Record<Lang, string>> = {
  verified: { ru: 'Подтверждено', en: 'Verified' },
  likely: { ru: 'Вероятно', en: 'Likely' },
  unverified: { ru: 'Не подтверждено', en: 'Unverified' },
}

export const BASIS_LABELS: Record<string, Record<Lang, string>> = {
  wikipedia_and_site: { ru: 'Описание построено по Wikipedia и официальному сайту', en: 'Description based on Wikipedia and the official site' },
  wikipedia_only: { ru: 'Описание построено только по Wikipedia', en: 'Description based on Wikipedia only' },
  site_only: { ru: 'Описание построено только по официальному сайту', en: 'Description based on the official site only' },
  insufficient: { ru: 'Недостаточно данных', en: 'Insufficient data' },
}

export const UI: Record<string, Record<Lang, string>> = {
  appTitle: { ru: 'Visual Campus', en: 'Visual Campus' },
  appTagline: { ru: 'Проверенный визуальный профиль университета за 30 секунд', en: 'Verified visual university profile in 30 seconds' },
  searchPlaceholder: { ru: 'Введите название университета', en: 'Enter university name' },
  searchButton: { ru: 'Найти', en: 'Search' },
  notFound: { ru: 'Университет не найден. Проверьте написание или введите официальное английское название.', en: 'University not found. Check the spelling or enter the official English name.' },
  correctedQuery: { ru: 'Показаны результаты по исправленному названию:', en: 'Results shown for corrected name:' },
  footer: { ru: 'Источники: Wikimedia Commons, Flickr, официальные сайты, Wikipedia. Для небольших вузов данных может быть мало — сервис сообщит об этом явно.', en: 'Sources: Wikimedia Commons, Flickr, official sites, Wikipedia. Small universities may have limited data — the service will say so explicitly.' },
  allCategories: { ru: 'Все', en: 'All' },
  showUnverified: { ru: 'Показать непроверенные', en: 'Show unverified' },
  distanceToCity: { ru: 'км до центра города', en: 'km to city center' },
  cachedBadge: { ru: 'Результат из кэша', en: 'Cached result' },
  refresh: { ru: 'Обновить', en: 'Refresh' },
  sourceLabel: { ru: 'Источник:', en: 'Source:' },
  openOriginal: { ru: 'Открыть оригинал', en: 'Open original' },
  sources: { ru: 'Источники:', en: 'Sources:' },
  stepSearch: { ru: 'Поиск', en: 'Search' },
  stepVerify: { ru: 'Проверка', en: 'Verification' },
  stepCategories: { ru: 'Категории', en: 'Categories' },
  stepProfile: { ru: 'Профиль', en: 'Profile' },
  statsBar: { ru: 'Нашли {found} → убрали {dupes} дублей и {irrel} нерелевантных → показываем {shown}', en: 'Found {found} → removed {dupes} duplicates and {irrel} irrelevant → showing {shown}' },
  noPhotosInCategory: { ru: 'Не удалось найти проверенные фото этой категории.', en: 'No verified photos found in this category.' },
  retryButton: { ru: 'Повторить', en: 'Retry' },
  networkError: { ru: 'Ошибка сети. Проверьте соединение.', en: 'Network error. Check your connection.' },
  exampleChips: { ru: 'Примеры:', en: 'Examples:' },
}
