import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './App.css'
import './styles/theme.css'
import Dashboard from './pages/Dashboard'
import AnalysisPage from './pages/Analysis'
import Login from './pages/Login'
import AdminPortal from './pages/AdminPortal'
import OrganizationSettings from './pages/OrganizationSettings'
import Layout from './components/Layout'
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
          <ProtectedRoute>
            <Layout>
              <Dashboard />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <Layout>
              <Dashboard />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/analysis"
        element={
          <ProtectedRoute>
            <Layout>
              <AnalysisPage />
            </Layout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <AdminRoute>
            <Layout>
              <AdminPortal />
            </Layout>
          </AdminRoute>
        }
      />
      <Route
        path="/organizations"
        element={
          <ProtectedRoute>
            <Layout>
              <OrganizationSettings />
            </Layout>
          </ProtectedRoute>
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
