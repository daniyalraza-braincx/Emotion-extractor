import { API_ENDPOINTS } from '../config';

const TOKEN_KEY = 'auth_token';

/**
 * Login with username and password
 * @param {string} username 
 * @param {string} password 
 * @param {number|null} organizationId - Optional organization ID for users
 * @returns {Promise<Object>} Response with access_token
 */
export async function login(username, password, organizationId = null) {
  const loginData = { username, password };
  if (organizationId) {
    loginData.organization_id = organizationId;
  }

  const response = await fetch(API_ENDPOINTS.LOGIN, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(loginData),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Login failed' }));
    throw new Error(error.detail || 'Login failed');
  }

  const data = await response.json();
  if (data.access_token) {
    localStorage.setItem(TOKEN_KEY, data.access_token);
  }
  return { ...data, success: true };
}

/**
 * Logout and remove token
 */
export function logout() {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * Get the current auth token
 * @returns {string|null}
 */
export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Check if user is authenticated
 * @returns {boolean}
 */
export function isAuthenticated() {
  return !!getToken();
}

/**
 * Verify if the current token is valid
 * @returns {Promise<boolean>}
 */
export async function verifyToken() {
  const token = getToken();
  if (!token) {
    return false;
  }

  try {
    const response = await fetch(API_ENDPOINTS.VERIFY, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${token}`,
      },
    });

    return response.ok;
  } catch {
    return false;
  }
}

/**
 * Get authorization header for API requests
 * @returns {Object}
 */
export function getAuthHeaders() {
  const token = getToken();
  if (!token) {
    return {};
  }
  return {
    'Authorization': `Bearer ${token}`,
  };
}

