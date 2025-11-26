import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './App.css'
import Dashboard from './pages/Dashboard'
import AnalysisPage from './pages/Analysis'
import Login from './pages/Login'
import AdminPortal from './pages/AdminPortal'
import OrganizationSettings from './pages/OrganizationSettings'
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

function AdminRoute({ children }) {
  const { authenticated, loading, isAdmin } = useAuth();

  if (loading) {
    return <div className="app-loading">Loading...</div>;
  }

  if (!authenticated) {
    return <Navigate to="/login" replace />;
  }

  if (!isAdmin) {
    return <Navigate to="/" replace />;
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
      <Route
        path="/admin"
        element={
          <div className="app-root">
            <AdminRoute>
              <AdminPortal />
            </AdminRoute>
          </div>
        }
      />
      <Route
        path="/organizations"
        element={
          <div className="app-root">
            <ProtectedRoute>
              <OrganizationSettings />
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
