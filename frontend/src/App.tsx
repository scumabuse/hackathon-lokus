import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useState, useEffect } from 'react'
import SearchPage from './pages/SearchPage'
import ProfilePage from './pages/ProfilePage'
import type { Lang } from './i18n'

export default function App() {
  const [lang, setLang] = useState<Lang>(() => {
    return (localStorage.getItem('lang') as Lang) || 'ru'
  })

  useEffect(() => {
    localStorage.setItem('lang', lang)
  }, [lang])

  const toggleLang = () => setLang(l => l === 'ru' ? 'en' : 'ru')

  return (
    <BrowserRouter>
      {/* Global Lang Toggle in a fixed subtle position, or part of navigation if needed */}
      <button 
        onClick={toggleLang}
        className="fixed bottom-4 right-4 z-50 bg-white shadow-md border border-slate-200 px-3 py-1.5 rounded-full text-xs font-semibold text-slate-600 hover:bg-slate-50 transition"
      >
        {lang === 'ru' ? 'EN' : 'RU'}
      </button>

      <Routes>
        <Route path="/" element={<SearchPage lang={lang} />} />
        <Route path="/u/:qid" element={<ProfilePage lang={lang} />} />
      </Routes>
    </BrowserRouter>
  )
}
