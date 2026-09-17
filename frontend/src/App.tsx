import { useEffect, useState } from 'react'

type Health = { status: string; version: string; time: string }

// Phase 0 placeholder page: proves the SPA builds and can reach /api/health.
export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((h: Health) => setHealth(h))
      .catch((e: Error) => setError(e.message))
  }, [])

  return (
    <main className="mx-auto max-w-3xl px-4 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">Visual Campus</h1>
      <p className="mt-2 text-slate-600">
        Проверенный визуальный профиль университета за 30 секунд.
      </p>
      <p className="mt-6 text-sm text-slate-500">
        API: {health ? `ok · ${health.version}` : error ? `недоступен (${error})` : '…'}
      </p>
    </main>
  )
}
