import { API_ENDPOINTS } from '../config';

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
      body: formData,
    });

    if (!response.ok) {
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
 * Fetches the list of Retell calls that are available for analysis
 * @returns {Promise<Array>} Array of calls
 */
export async function fetchRetellCalls() {
  const response = await fetch(API_ENDPOINTS.RETELL_CALLS);
  if (!response.ok) {
    throw new Error('Failed to fetch Retell calls');
  }

  const data = await response.json();
  return Array.isArray(data.calls) ? data.calls : [];
}

/**
 * Triggers a Hume analysis for a specific Retell call
 * @param {string} callId - The Retell call identifier
 * @returns {Promise<Object>} The analysis results
 */
export async function analyzeRetellCall(callId) {
  if (!callId) {
    throw new Error('callId is required');
  }

  const endpoint = API_ENDPOINTS.RETELL_ANALYZE(callId);
  const response = await fetch(endpoint, { method: 'POST' });

  if (!response.ok) {
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
  const response = await fetch(endpoint);

  if (!response.ok) {
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

