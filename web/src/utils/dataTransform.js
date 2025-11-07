/**
 * Transforms API response data into chart-compatible format
 * Aggregates emotions into 10-second intervals to reduce chart density
 * Dynamically extracts all emotions from the API response (top 3 per segment)
 * @param {Object} apiResponse - The API response containing prosody data
 * @returns {Object} Object with chartData array and emotions array
 */
export function transformApiDataToChart(apiResponse) {
  const { results } = apiResponse;
  
  if (!results || !results.prosody || results.prosody.length === 0) {
    return { chartData: [], emotions: [] };
  }

  // First, collect all unique emotions across all segments
  const allEmotions = new Set();
  results.prosody.forEach(segment => {
    if (segment.top_emotions && Array.isArray(segment.top_emotions)) {
      segment.top_emotions.forEach(emotion => {
        if (emotion.name) {
          allEmotions.add(emotion.name);
        }
      });
    }
  });

  // Convert to sorted array for consistent ordering
  const emotionsList = Array.from(allEmotions).sort();

  // Group segments into 10-second intervals
  const INTERVAL_SIZE = 10; // 10 seconds
  const intervalMap = new Map(); // Map of interval_start -> aggregated emotions

  // Find the time range of the data
  const timeStarts = results.prosody.map(s => s.time_start).filter(t => t !== undefined);
  const minTime = timeStarts.length > 0 ? Math.min(...timeStarts) : 0;
  const maxTime = timeStarts.length > 0 ? Math.max(...timeStarts) : 0;
  
  // Ensure we always have an interval starting at 0 if data exists
  const firstInterval = Math.floor(minTime / INTERVAL_SIZE) * INTERVAL_SIZE;
  const lastInterval = Math.floor(maxTime / INTERVAL_SIZE) * INTERVAL_SIZE;

  results.prosody.forEach(segment => {
    const { time_start, top_emotions } = segment;
    
    // Calculate which 10-second interval this segment belongs to
    const intervalStart = Math.floor(time_start / INTERVAL_SIZE) * INTERVAL_SIZE;
    
    // Initialize interval if it doesn't exist
    if (!intervalMap.has(intervalStart)) {
      const intervalData = {
        time: intervalStart,
        emotions: {}
      };
      // Initialize all emotions to 0 for this interval
      emotionsList.forEach(emotion => {
        intervalData.emotions[emotion] = 0;
      });
      intervalMap.set(intervalStart, intervalData);
    }

    // Aggregate emotions for this interval
    // Use maximum score for each emotion within the interval
    if (top_emotions && Array.isArray(top_emotions)) {
      top_emotions.forEach(emotion => {
        if (emotion.name && emotion.score !== undefined) {
          const currentMax = intervalMap.get(intervalStart).emotions[emotion.name] || 0;
          // Take the maximum score for each emotion in the interval
          intervalMap.get(intervalStart).emotions[emotion.name] = Math.max(currentMax, emotion.score);
        }
      });
    }
  });

  // Always include interval 0 if we have any data, even if empty
  if (intervalMap.size > 0 && !intervalMap.has(0) && firstInterval >= 0) {
    const intervalData = {
      time: 0,
      emotions: {}
    };
    emotionsList.forEach(emotion => {
      intervalData.emotions[emotion] = 0;
    });
    intervalMap.set(0, intervalData);
  }

  // Convert interval map to chart data array
  const chartData = Array.from(intervalMap.values())
    .map(interval => ({
      time: interval.time,
      ...interval.emotions
    }))
    .sort((a, b) => a.time - b.time);

  return { chartData, emotions: emotionsList };
}

/**
 * Extracts all unique emotions from the API response
 * @param {Object} apiResponse - The API response
 * @returns {Array} Array of unique emotion names
 */
export function extractUniqueEmotions(apiResponse) {
  const { results } = apiResponse;
  const emotions = new Set();

  if (results?.prosody) {
    results.prosody.forEach(segment => {
      segment.top_emotions?.forEach(emotion => {
        emotions.add(emotion.name);
      });
    });
  }

  if (results?.burst) {
    results.burst.forEach(segment => {
      segment.top_emotions?.forEach(emotion => {
        emotions.add(emotion.name);
      });
    });
  }

  return Array.from(emotions);
}

