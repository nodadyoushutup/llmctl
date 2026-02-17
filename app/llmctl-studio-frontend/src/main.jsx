import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { runtimeConfig } from './config/runtime'
import '@fortawesome/fontawesome-free/css/all.min.css'
import './styles.css'

const basename = runtimeConfig.webBasePath === '/' ? undefined : runtimeConfig.webBasePath

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter basename={basename}>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
