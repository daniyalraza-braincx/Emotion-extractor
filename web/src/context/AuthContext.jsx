import { createContext, useContext, useState, useEffect } from 'react';
import { login as authLogin, logout as authLogout, verifyToken, isAuthenticated as checkAuth } from '../services/auth';
import { getCurrentUser, switchOrganization as apiSwitchOrganization } from '../services/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState(null);
  const [currentOrganization, setCurrentOrganization] = useState(null);
  const [organizations, setOrganizations] = useState([]);

  useEffect(() => {
    // Check if user is authenticated on mount
    const checkAuthStatus = async () => {
      if (checkAuth()) {
        const isValid = await verifyToken();
        if (isValid) {
          setAuthenticated(true);
          // Fetch user info and organizations
          try {
            await fetchUserInfo();
          } catch (error) {
            console.error('Failed to fetch user info:', error);
            authLogout();
            setAuthenticated(false);
          }
        } else {
          authLogout();
          setAuthenticated(false);
        }
      }
      setLoading(false);
    };

    checkAuthStatus();
  }, []);

  const fetchUserInfo = async () => {
    try {
      const response = await getCurrentUser();
      if (response.success) {
        setUser(response.user);
        setOrganizations(response.organizations || []);
        setCurrentOrganization(response.current_organization || null);
      }
    } catch (error) {
      console.error('Error fetching user info:', error);
      throw error;
    }
  };

  const login = async (username, password, organizationId = null) => {
    try {
      const loginData = { username, password };
      if (organizationId) {
        loginData.organization_id = organizationId;
      }
      const response = await authLogin(username, password, organizationId);
      if (response.success) {
        setAuthenticated(true);
        // Fetch user info after login
        await fetchUserInfo();
        return { success: true };
      }
      return { success: false, error: 'Login failed' };
    } catch (error) {
      return { success: false, error: error.message };
    }
  };

  const logout = () => {
    authLogout();
    setAuthenticated(false);
    setUser(null);
    setCurrentOrganization(null);
    setOrganizations([]);
  };

  const switchOrganization = async (organizationId) => {
    try {
      const response = await apiSwitchOrganization(organizationId);
      if (response.success && response.organization) {
        setCurrentOrganization(response.organization);
        // Refresh user info to get updated organization list
        await fetchUserInfo();
        return { success: true, organization: response.organization };
      }
      return { success: false, error: 'Failed to switch organization' };
    } catch (error) {
      return { success: false, error: error.message };
    }
  };

  return (
    <AuthContext.Provider value={{ 
      authenticated, 
      loading, 
      user,
      currentOrganization,
      organizations,
      login, 
      logout,
      switchOrganization,
      fetchUserInfo,
      isAdmin: user?.role === 'admin'
    }}>
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
