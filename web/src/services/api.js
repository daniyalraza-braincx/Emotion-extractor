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

