// API Configuration
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const API_ENDPOINTS = {
  ANALYZE: `${API_BASE_URL}/analyze`,
  HEALTH: `${API_BASE_URL}/`,
  LOGIN: `${API_BASE_URL}/auth/login`,
  LOGOUT: `${API_BASE_URL}/auth/logout`,
  VERIFY: `${API_BASE_URL}/auth/verify`,
  ME: `${API_BASE_URL}/auth/me`,
  SWITCH_ORG: `${API_BASE_URL}/auth/switch-organization`,
  RETELL_CALLS: `${API_BASE_URL}/retell/calls`,
  RETELL_ANALYZE: (callId) => `${API_BASE_URL}/retell/calls/${callId}/analyze`,
  RETELL_ANALYSIS: (callId) => `${API_BASE_URL}/retell/calls/${callId}/analysis`,
  // Admin endpoints
  ADMIN_USERS: `${API_BASE_URL}/admin/users`,
  ADMIN_USER_ORGS: (userId) => `${API_BASE_URL}/admin/users/${userId}/organizations`,
  ADMIN_ORGS: `${API_BASE_URL}/admin/organizations`,
  ADMIN_ORGS_ALL: `${API_BASE_URL}/admin/organizations/all`,
  // Organization endpoints
  ORGS: `${API_BASE_URL}/organizations`,
  ORGS_AGENTS: (orgId) => `${API_BASE_URL}/organizations/${orgId}/agents`,
  AGENTS_ALL: `${API_BASE_URL}/agents/all`,
};

