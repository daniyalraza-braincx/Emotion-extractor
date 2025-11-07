// API Configuration
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const API_ENDPOINTS = {
  ANALYZE: `${API_BASE_URL}/analyze`,
  HEALTH: `${API_BASE_URL}/`,
  RETELL_CALLS: `${API_BASE_URL}/retell/calls`,
  RETELL_ANALYZE: (callId) => `${API_BASE_URL}/retell/calls/${callId}/analyze`,
  RETELL_ANALYSIS: (callId) => `${API_BASE_URL}/retell/calls/${callId}/analysis`,
};

