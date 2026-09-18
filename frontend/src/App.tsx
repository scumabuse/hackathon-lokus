import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { MotionConfig } from 'motion/react'
import SearchPage from './pages/SearchPage'
import ProfilePage from './pages/ProfilePage'
import type { Lang } from './i18n'

function readLang(): Lang {
  try {
    const stored = localStorage.getItem('lang')
    return stored === 'en' ? 'en' : 'ru'
  } catch {
    return 'ru'
  }
}

export default function App() {
  const [lang, setLang] = useState<Lang>(readLang)

  useEffect(() => {
    try {
      localStorage.setItem('lang', lang)
    } catch {
      // storage may be blocked; the choice then lives for the session only
    }
    document.documentElement.lang = lang
  }, [lang])

  const toggleLang = useCallback(() => setLang((l) => (l === 'ru' ? 'en' : 'ru')), [])

  return (
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<SearchPage lang={lang} onToggleLang={toggleLang} />} />
          <Route path="/u/:qid" element={<ProfilePage lang={lang} onToggleLang={toggleLang} />} />
        </Routes>
      </BrowserRouter>
    </MotionConfig>
  )
}
