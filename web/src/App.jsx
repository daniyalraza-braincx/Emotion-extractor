import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './App.css'
import Dashboard from './pages/Dashboard'
import AnalysisPage from './pages/Analysis'
import Login from './pages/Login'
import { AnalysisProvider } from './context/AnalysisContext'
import { AuthProvider, useAuth } from './context/AuthContext'

function ProtectedRoute({ children }) {
  const { authenticated, loading } = useAuth();

  if (loading) {
    return <div className="app-loading">Loading...</div>;
  }

  if (!authenticated) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

function PublicRoute({ children }) {
  const { authenticated, loading } = useAuth();

  if (loading) {
    return <div className="app-loading">Loading...</div>;
  }

  if (authenticated) {
    return <Navigate to="/" replace />;
  }

  return children;
}

function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicRoute>
            <Login />
          </PublicRoute>
        }
      />
      <Route
        path="/"
        element={
          <div className="app-root">
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          </div>
        }
      />
      <Route
        path="/analysis"
        element={
          <div className="app-root">
            <ProtectedRoute>
              <AnalysisPage />
            </ProtectedRoute>
          </div>
        }
      />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <AuthProvider>
      <AnalysisProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AnalysisProvider>
    </AuthProvider>
  )
}

export default App
