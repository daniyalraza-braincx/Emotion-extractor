// API Configuration
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const API_ENDPOINTS = {
  ANALYZE: `${API_BASE_URL}/analyze`,
  HEALTH: `${API_BASE_URL}/`,
};

