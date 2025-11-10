import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './App.css'
import Dashboard from './pages/Dashboard'
import AnalysisPage from './pages/Analysis'
import { AnalysisProvider } from './context/AnalysisContext'

function App() {
  return (
    <AnalysisProvider>
      <BrowserRouter>
        <div className="app-root">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/analysis" element={<AnalysisPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </BrowserRouter>
    </AnalysisProvider>
  )
}

export default App
