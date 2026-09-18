import React from 'react'
import ReactDOM from 'react-dom/client'
// Self-hosted fonts (B3): paths verified in node_modules/@fontsource/*/.
import '@fontsource/instrument-serif/index.css'
import '@fontsource/instrument-sans/400.css'
import '@fontsource/instrument-sans/500.css'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
