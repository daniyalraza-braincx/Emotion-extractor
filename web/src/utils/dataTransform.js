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

  // Collect all unique emotions across segments
  const allEmotions = new Set();
  results.prosody.forEach((segment) => {
    segment.top_emotions?.forEach((emotion) => {
      if (emotion?.name) {
        allEmotions.add(emotion.name);
      }
    });
  });

  const emotionsList = Array.from(allEmotions).sort();

  const INTERVAL_SIZE = 10;
  const intervalMap = new Map();

  const timeBounds = results.prosody.reduce(
    (acc, segment) => {
      const start = typeof segment.time_start === 'number' ? segment.time_start : acc.min;
      const end = typeof segment.time_end === 'number' ? segment.time_end : start;
      return {
        min: Math.min(acc.min, start),
        max: Math.max(acc.max, end)
      };
    },
    { min: Infinity, max: 0 }
  );

  const minInterval = Math.max(0, Math.floor(timeBounds.min / INTERVAL_SIZE) * INTERVAL_SIZE);
  const maxInterval = Math.floor(timeBounds.max / INTERVAL_SIZE) * INTERVAL_SIZE;

  // Pre-create intervals to ensure contiguous coverage
  for (let intervalStart = minInterval; intervalStart <= maxInterval; intervalStart += INTERVAL_SIZE) {
    intervalMap.set(intervalStart, {
      intervalStart,
      intervalEnd: intervalStart + INTERVAL_SIZE,
      emotions: {}
    });
  }

  results.prosody.forEach((segment) => {
    const timeStart = typeof segment.time_start === 'number' ? segment.time_start : 0;
    const intervalStart = Math.floor(timeStart / INTERVAL_SIZE) * INTERVAL_SIZE;

    if (!intervalMap.has(intervalStart)) {
      intervalMap.set(intervalStart, {
        intervalStart,
        intervalEnd: intervalStart + INTERVAL_SIZE,
        emotions: {}
      });
    }

    const intervalData = intervalMap.get(intervalStart);

    segment.top_emotions?.forEach((emotion) => {
      if (!emotion?.name || typeof emotion.score !== 'number') {
        return;
      }

      const currentScore = intervalData.emotions[emotion.name] ?? 0;
      intervalData.emotions[emotion.name] = Math.max(currentScore, emotion.score);
    });
  });

  const chartData = Array.from(intervalMap.values())
    .sort((a, b) => a.intervalStart - b.intervalStart)
    .map((interval) => {
      const emotionEntries = Object.entries(interval.emotions);

      const topEmotionEntry = emotionEntries.reduce(
        (best, [emotionName, value]) => {
          if (!best || value > best.value) {
            return { name: emotionName, value };
          }
          return best;
        },
        null
      );

      return {
        time: interval.intervalStart + INTERVAL_SIZE / 2,
        intervalStart: interval.intervalStart,
        intervalEnd: interval.intervalEnd,
        topEmotion: topEmotionEntry?.name || null,
        score: topEmotionEntry?.value ?? 0,
        emotions: interval.emotions
      };
    });

  return {
    chartData,
    emotions: emotionsList
  };
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

