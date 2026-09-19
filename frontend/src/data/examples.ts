import type { Category, DateKind } from '../types'

export interface ExampleUniversity {
  qid: string
  name: string
  name_ru: string
  city: string
  country: string
  photo: {
    thumb: string
    title: string
    width: number
    height: number
    category: Category
    source_label: string
    date_kind: DateKind
    date?: string
  }
  run: {
    verified: number
    shown: number
    total_ms: number
  }
}

export const EXAMPLES: ExampleUniversity[] = [
  {
    qid: 'Q49108',
    name: 'Massachusetts Institute of Technology',
    name_ru: 'Массачусетский технологический институт',
    city: 'Cambridge',
    country: 'United States',
    photo: {
      thumb: 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/MIT_Dome_night1_Edit.jpg/500px-MIT_Dome_night1_Edit.jpg',
      title: 'MIT Dome',
      width: 500,
      height: 375,
      category: 'campus',
      source_label: 'Wikimedia Commons',
      date_kind: 'taken',
      date: '2019-05-04'
    },
    run: { verified: 17, shown: 41, total_ms: 26514 }
  },
  {
    qid: 'Q2783344',
    name: 'Nazarbayev University',
    name_ru: 'Назарбаев Университет',
    city: 'Astana',
    country: 'Kazakhstan',
    photo: {
      thumb: 'https://upload.wikimedia.org/wikipedia/en/thumb/c/ca/NU_Building.jpg/500px-NU_Building.jpg',
      title: 'Nazarbayev University',
      width: 500,
      height: 333,
      category: 'campus',
      source_label: 'Wikimedia Commons',
      date_kind: 'taken',
      date: '2015-08-11'
    },
    run: { verified: 24, shown: 28, total_ms: 18171 }
  },
  {
    qid: 'Q427677',
    name: 'Al-Farabi Kazakh National University',
    name_ru: 'КазНУ им. аль-Фараби',
    city: 'Almaty',
    country: 'Kazakhstan',
    photo: {
      thumb: 'https://upload.wikimedia.org/wikipedia/commons/thumb/7/72/Al-Farabi_KazNU_rektorat.jpg/500px-Al-Farabi_KazNU_rektorat.jpg',
      title: 'KazNU campus',
      width: 500,
      height: 333,
      category: 'campus',
      source_label: 'Wikimedia Commons',
      date_kind: 'taken',
      date: '2016-10-02'
    },
    run: { verified: 19, shown: 31, total_ms: 17578 }
  },
  {
    qid: 'Q11942',
    name: 'ETH Zurich',
    name_ru: 'Швейцарская высшая техническая школа Цюриха',
    city: 'Zurich',
    country: 'Switzerland',
    photo: {
      thumb: 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/38/ETH_Z%C3%BCrich_-_Hauptgeb%C3%A4ude_-_Unispital_2012-07-30_07-57-03_ShiftN.jpg/500px-ETH_Z%C3%BCrich_-_Hauptgeb%C3%A4ude_-_Unispital_2012-07-30_07-57-03_ShiftN.jpg',
      title: 'ETH Zurich Main Building',
      width: 500,
      height: 333,
      category: 'campus',
      source_label: 'Wikimedia Commons',
      date_kind: 'taken',
      date: '2014-07-28'
    },
    run: { verified: 37, shown: 39, total_ms: 22937 }
  },
  {
    qid: 'Q13164',
    name: 'Lomonosov Moscow State University',
    name_ru: 'МГУ им. М.В. Ломоносова',
    city: 'Moscow',
    country: 'Russia',
    photo: {
      thumb: 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a0/Moscow_State_University_crop.jpg/500px-Moscow_State_University_crop.jpg',
      title: 'MSU Main Building',
      width: 500,
      height: 333,
      category: 'campus',
      source_label: 'Wikimedia Commons',
      date_kind: 'taken',
      date: '2010-09-04'
    },
    run: { verified: 16, shown: 28, total_ms: 19093 }
  },
  {
    qid: 'Q7842',
    name: 'University of Tokyo',
    name_ru: 'Токийский университет',
    city: 'Tokyo',
    country: 'Japan',
    photo: {
      thumb: 'https://upload.wikimedia.org/wikipedia/commons/thumb/d/de/Yasuda_Auditorium.jpg/500px-Yasuda_Auditorium.jpg',
      title: 'Yasuda Auditorium',
      width: 500,
      height: 333,
      category: 'campus',
      source_label: 'Wikimedia Commons',
      date_kind: 'taken',
      date: '2017-04-22'
    },
    run: { verified: 20, shown: 42, total_ms: 26500 }
  }
]

export const CHIP_QIDS = ['Q49108', 'Q2783344', 'Q11942', 'Q427677']
export const MOSAIC_QIDS = ['Q49108', 'Q2783344', 'Q11942']

export function exampleByQid(qid: string): ExampleUniversity | undefined {
  return EXAMPLES.find(e => e.qid === qid)
}
