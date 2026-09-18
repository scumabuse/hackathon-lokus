/** Frontend type definitions — mirrors SPEC Section 5 pydantic models exactly. */

export type DateKind = 'taken' | 'published' | 'uploaded' | 'unknown'
export type CategorySource = 'vision' | 'heuristic' | 'source_hint'
export type DescriptionBasis = 'wikipedia_and_site' | 'wikipedia_only' | 'site_only' | 'insufficient'
export type Verification = 'verified' | 'likely' | 'unverified'

export type Category =
  | 'campus'
  | 'dormitory'
  | 'classroom'
  | 'library'
  | 'lab'
  | 'sport'
  | 'student_life'
  | 'city'
  | 'other'

export type SourceType =
  | 'wikidata_p18'
  | 'official_site'
  | 'commons_category'
  | 'commons_geo'
  | 'flickr_geo'
  | 'commons_search'
  | 'web_search'
  | 'city_commons'

export type ReasonCode =
  | 'wikidata_main_image'
  | 'official_site_source'
  | 'commons_category_source'
  | 'commons_search_source'
  | 'commons_geo_source'
  | 'flickr_geo_source'
  | 'web_search_source'
  | 'city_category_source'
  | 'name_in_metadata'
  | 'name_on_sign'
  | 'geo_within_300m'
  | 'geo_within_1km'
  | 'vision_consistent'
  | 'vision_unavailable'
  | 'vision_timeout'
  | 'category_heuristic'
  | 'cached_result'

export type WarningCode =
  | 'low_data'
  | 'no_coordinates'
  | 'no_commons_category'
  | 'no_official_site'
  | 'source_unavailable'
  | 'vision_unavailable'
  | 'time_budget_exceeded'
  | 'served_from_cache'
  | 'ambiguous_name'
  | 'missing_category'
  | 'queued'

export interface Coordinates {
  lat: number
  lon: number
}

export interface Candidate {
  qid: string
  label: string
  description?: string
  country?: string
  city?: string
}

export interface SearchResponse {
  query: string
  candidates: Candidate[]
  suggestions_used: boolean
  corrected_query?: string
}

export interface Place {
  qid?: string
  name: string
  coords?: Coordinates
  wikipedia_url?: string
  commons_category?: string
}

export interface UniversityHeader {
  qid: string
  name: string
  local_name?: string
  aliases: string[]
  country?: string
  city?: Place
  coords?: Coordinates
  official_website?: string
  wikipedia_url?: string
  commons_category?: string
  logo_url?: string
  distance_to_city_center_km?: number
  cached: boolean
  cached_at?: string
}

export interface SourceLink {
  title: string
  url: string
}

export interface Description {
  text_ru: string
  text_en: string
  sources: SourceLink[]
  basis: DescriptionBasis
}

export interface Photo {
  id: string
  thumb_url: string
  image_url: string
  source_page_url: string
  source_type: SourceType
  source_label: string
  title?: string
  author?: string
  license?: string
  date?: string
  date_kind: DateKind
  category: Category
  category_source: CategorySource
  width?: number
  height?: number
  confidence: number
  verification: Verification
  reasons: ReasonCode[]
  geo?: Coordinates
  distance_m?: number
  visible_text?: string
  vision_reason?: string
}

export interface Stats {
  found: number
  duplicates_removed: number
  irrelevant_removed: number
  shown: number
  hidden_unverified: number
  per_source: Record<string, number>
  timings_ms: Record<string, number>
  total_ms: number
}

export interface Warning {
  code: WarningCode
  detail?: string
}

export interface Profile {
  header: UniversityHeader
  description?: Description
  photos: Photo[]
  stats: Stats
  warnings: Warning[]
  generated_at: string
}
