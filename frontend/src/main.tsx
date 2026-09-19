import React from 'react'
import ReactDOM from 'react-dom/client'
// Self-hosted variable fonts with Cyrillic subsets: paths verified in node_modules/@fontsource-variable/*/.
import '@fontsource-variable/playfair-display'
import '@fontsource-variable/playfair-display/wght-italic.css'
import '@fontsource-variable/inter'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
