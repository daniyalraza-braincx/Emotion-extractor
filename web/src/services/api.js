import { API_ENDPOINTS } from '../config';
import { getAuthHeaders, logout } from './auth';

/**
 * Analyzes an audio file by sending it to the backend API
 * @param {File} file - The audio file to analyze
 * @returns {Promise<Object>} The analysis results
 */
export async function analyzeAudioFile(file) {
  const formData = new FormData();
  formData.append('file', file);

  try {
    const response = await fetch(API_ENDPOINTS.ANALYZE, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: formData,
    });

    if (!response.ok) {
      // Handle expired token or forbidden
      if (response.status === 401 || response.status === 403) {
        logout();
        window.location.href = '/login';
        throw new Error('Your session has expired. Please log in again.');
      }

      let errorMessage = `Server error (${response.status})`;
      
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorMessage;
      } catch {
        // If response is not JSON, use status text
        errorMessage = response.statusText || errorMessage;
      }

      // Provide user-friendly error messages
      if (response.status === 404) {
        errorMessage = 'No emotion predictions found. The audio may not contain detectable speech.';
      } else if (response.status === 413) {
        errorMessage = 'File too large. Please upload a smaller audio file.';
      } else if (response.status >= 500) {
        errorMessage = 'Server error. Please try again later.';
      }

      throw new Error(errorMessage);
    }

    return await response.json();
  } catch (error) {
    // Handle network errors
    if (error.name === 'TypeError' && error.message.includes('fetch')) {
      throw new Error('Cannot connect to the server. Please make sure the API is running on http://localhost:8000');
    }
    // Re-throw other errors
    throw error;
  }
}

/**
 * Checks if the API is available
 * @returns {Promise<boolean>} True if API is available
 */
export async function checkApiHealth() {
  try {
    const response = await fetch(API_ENDPOINTS.HEALTH);
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * Fetches Retell calls with pagination support
 * @param {number} page - Page number (1-indexed)
 * @param {number} perPage - Number of items per page
 * @param {string} agentId - Optional agent ID to filter calls
 * @param {string} analysisStatus - Optional analysis status to filter calls (e.g., 'completed')
 * @returns {Promise<Object>} Response with calls array and pagination metadata
 */
export async function fetchRetellCalls(page = 1, perPage = 15, agentId = null, analysisStatus = null) {
  const url = new URL(API_ENDPOINTS.RETELL_CALLS);
  url.searchParams.set('page', String(page));
  url.searchParams.set('per_page', String(perPage));
  if (agentId) {
    url.searchParams.set('agent_id', agentId);
  }
  if (analysisStatus) {
    url.searchParams.set('analysis_status', analysisStatus);
  }

  const response = await fetch(url.toString(), {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    throw new Error('Failed to fetch Retell calls');
  }

  const data = await response.json();
  return {
    calls: Array.isArray(data.calls) ? data.calls : [],
    pagination: data.pagination || {
      page: page || 1,
      per_page: perPage,
      total: 0,
      total_pages: 1,
      has_next: false,
      has_prev: false,
    }
  };
}

/**
 * Triggers a Hume analysis for a specific Retell call
 * @param {string} callId - The Retell call identifier
 * @returns {Promise<Object>} The analysis results
 */
export async function analyzeRetellCall(callId, options = {}) {
  if (!callId) {
    throw new Error('callId is required');
  }

  const { force = false } = options;
  const endpoint = force
    ? `${API_ENDPOINTS.RETELL_ANALYZE(callId)}?force=true`
    : API_ENDPOINTS.RETELL_ANALYZE(callId);
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  return await response.json();
}

/**
 * Retrieves stored analysis results for a Retell call if available
 * @param {string} callId - The Retell call identifier
 * @returns {Promise<Object>} The analysis payload
 */
export async function getRetellCallAnalysis(callId) {
  if (!callId) {
    throw new Error('callId is required');
  }

  const endpoint = API_ENDPOINTS.RETELL_ANALYSIS(callId);
  const response = await fetch(endpoint, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    
    // 404 means analysis doesn't exist yet - this is expected and should be handled silently
    if (response.status === 404) {
      const notFoundError = new Error('Analysis not found');
      notFoundError.status = 404;
      notFoundError.isNotFound = true; // Flag to identify this as a "not found" case
      throw notFoundError;
    }
    
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  return await response.json();
}

/**
 * Get current user info and organizations
 * @returns {Promise<Object>} User info with organizations
 */
export async function getCurrentUser() {
  const response = await fetch(API_ENDPOINTS.ME, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    throw new Error('Failed to fetch user info');
  }

  return await response.json();
}

/**
 * Switch to a different organization
 * @param {number} organizationId - The organization ID to switch to
 * @returns {Promise<Object>} New token and organization info
 */
export async function switchOrganization(organizationId) {
  const response = await fetch(API_ENDPOINTS.SWITCH_ORG, {
    method: 'POST',
    headers: {
      ...getAuthHeaders(),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ organization_id: organizationId }),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  const data = await response.json();
  // Update token in localStorage
  if (data.access_token) {
    localStorage.setItem('auth_token', data.access_token);
  }
  return data;
}

// Admin endpoints
/**
 * Create a new user (admin only)
 * @param {Object} userData - User data (username, password, role, email)
 * @returns {Promise<Object>} Created user info
 */
export async function createUser(userData) {
  const response = await fetch(API_ENDPOINTS.ADMIN_USERS, {
    method: 'POST',
    headers: {
      ...getAuthHeaders(),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(userData),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  return await response.json();
}

/**
 * List all users (admin only)
 * @param {number} page - Page number
 * @param {number} perPage - Items per page
 * @param {string} role - Filter by role (optional)
 * @param {boolean} isActive - Filter by active status (optional)
 * @returns {Promise<Object>} Users list with pagination
 */
export async function listUsers(page = 1, perPage = 15, role = null, isActive = null) {
  const url = new URL(API_ENDPOINTS.ADMIN_USERS);
  url.searchParams.set('page', String(page));
  url.searchParams.set('per_page', String(perPage));
  if (role) url.searchParams.set('role', role);
  if (isActive !== null) url.searchParams.set('is_active', String(isActive));

  const response = await fetch(url.toString(), {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    throw new Error('Failed to fetch users');
  }

  return await response.json();
}

/**
 * Update a user (admin only)
 * @param {number} userId - User ID
 * @param {Object} userData - Updated user data
 * @returns {Promise<Object>} Updated user info
 */
export async function updateUser(userId, userData) {
  const response = await fetch(`${API_ENDPOINTS.ADMIN_USERS}/${userId}`, {
    method: 'PUT',
    headers: {
      ...getAuthHeaders(),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(userData),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  return await response.json();
}

/**
 * Deactivate a user (admin only)
 * @param {number} userId - User ID
 * @returns {Promise<Object>} Success message
 */
export async function deleteUser(userId) {
  const response = await fetch(`${API_ENDPOINTS.ADMIN_USERS}/${userId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  return await response.json();
}

/**
 * Get organizations for a specific user (admin only)
 * @param {number} userId - User ID
 * @returns {Promise<Object>} Organizations list for the user
 */
export async function getUserOrganizationsAdmin(userId) {
  const response = await fetch(API_ENDPOINTS.ADMIN_USER_ORGS(userId), {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  return await response.json();
}

/**
 * List all organizations (admin only)
 * @param {number} page - Page number
 * @param {number} perPage - Items per page
 * @returns {Promise<Object>} Organizations list with pagination
 */
export async function listAllOrganizations(page = 1, perPage = 15) {
  const url = new URL(API_ENDPOINTS.ADMIN_ORGS);
  url.searchParams.set('page', String(page));
  url.searchParams.set('per_page', String(perPage));

  const response = await fetch(url.toString(), {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    throw new Error('Failed to fetch organizations');
  }

  return await response.json();
}

// Organization endpoints
/**
 * Create a new organization
 * @param {string} name - Organization name
 * @returns {Promise<Object>} Created organization info
 */
export async function createOrganization(name) {
  const response = await fetch(API_ENDPOINTS.ORGS, {
    method: 'POST',
    headers: {
      ...getAuthHeaders(),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ name }),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  const data = await response.json();
  
  // If a new token is returned (with organization), save it
  if (data.access_token) {
    localStorage.setItem('auth_token', data.access_token);
  }

  return data;
}

/**
 * Get user's organizations
 * @returns {Promise<Object>} Organizations list
 */
export async function getUserOrganizations() {
  const response = await fetch(API_ENDPOINTS.ORGS, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    throw new Error('Failed to fetch organizations');
  }

  return await response.json();
}

/**
 * Update an organization
 * @param {number} orgId - Organization ID
 * @param {Object} orgData - Updated organization data
 * @returns {Promise<Object>} Updated organization info
 */
export async function updateOrganization(orgId, orgData) {
  const response = await fetch(`${API_ENDPOINTS.ORGS}/${orgId}`, {
    method: 'PUT',
    headers: {
      ...getAuthHeaders(),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(orgData),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  return await response.json();
}

/**
 * Delete an organization
 * @param {number} orgId - Organization ID
 * @returns {Promise<Object>} Success message
 */
export async function deleteOrganization(orgId) {
  const response = await fetch(`${API_ENDPOINTS.ORGS}/${orgId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  return await response.json();
}

/**
 * Get list of saved agents for an organization
 * @param {number} orgId - Organization ID
 * @returns {Promise<Object>} List of agents with their IDs and names
 */
export async function getOrganizationAgents(orgId) {
  const response = await fetch(API_ENDPOINTS.ORGS_AGENTS(orgId), {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  return await response.json();
}

/**
 * Add a new agent to an organization
 * @param {number} orgId - Organization ID
 * @param {string} agentId - Agent ID
 * @param {string} agentName - Optional agent name
 * @returns {Promise<Object>} Created agent info
 */
export async function addOrganizationAgent(orgId, agentId, agentName = null) {
  const response = await fetch(API_ENDPOINTS.ORGS_AGENTS(orgId), {
    method: 'POST',
    headers: {
      ...getAuthHeaders(),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      agent_id: agentId,
      agent_name: agentName,
    }),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  return await response.json();
}

/**
 * Delete an agent from an organization
 * @param {number} orgId - Organization ID
 * @param {number} agentId - Agent record ID (not agent_id string)
 * @returns {Promise<Object>} Success message
 */
export async function deleteOrganizationAgent(orgId, agentId) {
  const response = await fetch(`${API_ENDPOINTS.ORGS_AGENTS(orgId)}/${agentId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      logout();
      window.location.href = '/login';
      throw new Error('Your session has expired. Please log in again.');
    }
    let errorMessage = `Server error (${response.status})`;
    try {
      const errorData = await response.json();
      errorMessage = errorData.detail || errorMessage;
    } catch {
      errorMessage = response.statusText || errorMessage;
    }
    throw new Error(errorMessage);
  }

  return await response.json();
}
