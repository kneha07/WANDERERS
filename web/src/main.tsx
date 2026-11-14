import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// No StrictMode: its double mount in dev would start every cold (slow) search twice.
createRoot(document.getElementById('root')!).render(<App />)
