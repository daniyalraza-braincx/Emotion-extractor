import { createContext, useContext, useState, useEffect } from 'react';
import { login as authLogin, logout as authLogout, verifyToken, isAuthenticated as checkAuth } from '../services/auth';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if user is authenticated on mount
    const checkAuthStatus = async () => {
      if (checkAuth()) {
        const isValid = await verifyToken();
        setAuthenticated(isValid);
        if (!isValid) {
          authLogout();
        }
      }
      setLoading(false);
    };

    checkAuthStatus();
  }, []);

  const login = async (username, password) => {
    try {
      await authLogin(username, password);
      setAuthenticated(true);
      return { success: true };
    } catch (error) {
      return { success: false, error: error.message };
    }
  };

  const logout = () => {
    authLogout();
    setAuthenticated(false);
  };

  return (
    <AuthContext.Provider value={{ authenticated, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}

