/**
 * Transforms API response data into chart-compatible format
 * Aggregates emotions into 10-second intervals to reduce chart density
 * Dynamically extracts all emotions from the API response (top 3 per segment)
 * @param {Object} apiResponse - The API response containing prosody data
 * @returns {Object} Object with chartData array and emotions array
 */
function normalizeSpeakerName(rawSpeaker) {
  if (!rawSpeaker) {
    return null;
  }

  const value = String(rawSpeaker).trim();
  if (!value) {
    return null;
  }

  const normalized = value.toLowerCase();
  if (['customer', 'user', 'caller'].includes(normalized)) {
    return 'Customer';
  }
  if (['agent', 'assistant', 'rep', 'representative'].includes(normalized)) {
    return 'Agent';
  }

  return value.charAt(0).toUpperCase() + value.slice(1);
}

function buildTranscriptSegments(metadata) {
  const segments = Array.isArray(metadata?.retell_transcript_segments)
    ? metadata.retell_transcript_segments
    : [];

  return segments
    .map((segment) => {
      const speaker = normalizeSpeakerName(segment?.speaker);
      const start = Number(segment?.start);
      const end = Number(segment?.end);

      if (!speaker || Number.isNaN(start) || Number.isNaN(end)) {
        return null;
      }

      return {
        speaker,
        start,
        end,
        text: segment?.text || segment?.content || ''
      };
    })
    .filter(Boolean);
}

function findTranscriptSpeaker(timeStart, timeEnd, transcriptSegments) {
  if (!Array.isArray(transcriptSegments) || transcriptSegments.length === 0) {
    return null;
  }

  let bestMatch = null;
  let bestOverlap = 0;

  transcriptSegments.forEach((segment) => {
    const overlap = Math.max(0, Math.min(timeEnd, segment.end) - Math.max(timeStart, segment.start));
    if (overlap > bestOverlap) {
      bestOverlap = overlap;
      bestMatch = segment;
    }
  });

  return bestMatch ? bestMatch.speaker : null;
}

function getDominantEmotionForRange(rangeStart, rangeEnd, prosodySegments) {
  if (!Array.isArray(prosodySegments) || prosodySegments.length === 0) {
    return null;
  }

  let bestEmotion = null;
  let bestWeightedScore = 0;

  prosodySegments.forEach((segment) => {
    const overlap = Math.max(0, Math.min(rangeEnd, segment.end) - Math.max(rangeStart, segment.start));
    if (overlap <= 0) {
      return;
    }

    const emotion = segment.dominantEmotion;
    if (emotion && typeof emotion.score === 'number') {
      const weightedScore = overlap * emotion.score;
      if (weightedScore > bestWeightedScore) {
        bestWeightedScore = weightedScore;
        bestEmotion = emotion;
      }
    }
  });

  return bestEmotion;
}

export function transformApiDataToChart(apiResponse) {
  const { results } = apiResponse;

  if (!results || !results.prosody || results.prosody.length === 0) {
    return {
      chartData: [],
      emotions: [],
      speakerTimeline: {
        duration: 0,
        speakers: [],
        segments: {}
      }
    };
  }

  // Collect all unique emotions across segments
  const allEmotions = new Set();
  const transcriptSegments = buildTranscriptSegments(results?.metadata);
  const baseSpeakers = ['Customer', 'Agent'];
  const speakerSegmentsMap = new Map();
  baseSpeakers.forEach((speaker) => speakerSegmentsMap.set(speaker, []));

  let latestTime = 0;

  const prosodySegments = [];
  let lastKnownSpeaker = null;

  results.prosody.forEach((segment) => {
    const timeStart = typeof segment.time_start === 'number' ? segment.time_start : null;
    const timeEnd = typeof segment.time_end === 'number' ? segment.time_end : timeStart;

    if (timeStart === null || timeEnd === null || Number.isNaN(timeStart) || Number.isNaN(timeEnd)) {
      return;
    }

    const emotionList = Array.isArray(segment.top_emotions)
      ? segment.top_emotions.filter((emotion) => emotion?.name && typeof emotion.score === 'number')
      : [];

    emotionList.forEach((emotion) => {
      allEmotions.add(emotion.name);
    });

    const sortedEmotions = emotionList
      .slice()
      .sort((a, b) => (typeof b.score === 'number' ? b.score : 0) - (typeof a.score === 'number' ? a.score : 0));
    const dominantEmotion = sortedEmotions[0] || null;

    let speaker = normalizeSpeakerName(segment.speaker);
    if (!speaker) {
      speaker = findTranscriptSpeaker(timeStart, timeEnd, transcriptSegments) || null;
    }
    if (!speaker) {
      speaker = 'Unknown';
    } else if (speaker !== 'Unknown') {
      lastKnownSpeaker = speaker;
    }

    if (speaker === 'Unknown' && lastKnownSpeaker) {
      speaker = lastKnownSpeaker;
    }

    latestTime = Math.max(latestTime, timeEnd);

    prosodySegments.push({
      start: timeStart,
      end: timeEnd,
      emotions: emotionList,
      dominantEmotion,
      speaker,
      text: segment.transcript_text || segment.text || ''
    });

    if (!speakerSegmentsMap.has(speaker)) {
      speakerSegmentsMap.set(speaker, []);
    }

    speakerSegmentsMap.get(speaker).push({
      start: timeStart,
      end: timeEnd,
      topEmotion: dominantEmotion?.name || null,
      score: typeof dominantEmotion?.score === 'number' ? dominantEmotion.score : null,
      text: segment.transcript_text || segment.text || ''
    });
  });

  const emotionsList = Array.from(allEmotions).sort();

  const INTERVAL_SIZE = 10;
  const intervalMap = new Map();

  const timeBounds = prosodySegments.reduce(
    (acc, segment) => ({
      min: Math.min(acc.min, segment.start),
      max: Math.max(acc.max, segment.end)
    }),
    { min: Infinity, max: 0 }
  );

  const hasValidBounds = Number.isFinite(timeBounds.min) && Number.isFinite(timeBounds.max) && timeBounds.min !== Infinity;
  const minInterval = hasValidBounds ? Math.max(0, Math.floor(timeBounds.min / INTERVAL_SIZE) * INTERVAL_SIZE) : 0;
  const maxInterval = hasValidBounds ? Math.floor(timeBounds.max / INTERVAL_SIZE) * INTERVAL_SIZE : 0;

  // Pre-create intervals to ensure contiguous coverage
  if (hasValidBounds) {
    for (let intervalStart = minInterval; intervalStart <= maxInterval; intervalStart += INTERVAL_SIZE) {
      intervalMap.set(intervalStart, {
        intervalStart,
        intervalEnd: intervalStart + INTERVAL_SIZE,
        emotions: {}
      });
    }
  }

  prosodySegments.forEach((segment) => {
    const intervalStart = Math.floor(segment.start / INTERVAL_SIZE) * INTERVAL_SIZE;

    if (!intervalMap.has(intervalStart)) {
      intervalMap.set(intervalStart, {
        intervalStart,
        intervalEnd: intervalStart + INTERVAL_SIZE,
        emotions: {}
      });
    }

    const intervalData = intervalMap.get(intervalStart);

    segment.emotions.forEach((emotion) => {
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

  const speakerTimelineSegmentsMap = new Map();
  baseSpeakers.forEach((speaker) => {
    speakerTimelineSegmentsMap.set(speaker, []);
  });

  // Start with prosody-derived segments (most reliable for speech spans)
  speakerSegmentsMap.forEach((segments, speaker) => {
    if (!speakerTimelineSegmentsMap.has(speaker)) {
      speakerTimelineSegmentsMap.set(speaker, []);
    }
    speakerTimelineSegmentsMap.get(speaker).push(...segments);
  });

  // If transcript segments exist, use them to fill gaps where we have no prosody data
  if (transcriptSegments.length > 0) {
    transcriptSegments.forEach((segment) => {
      const speaker = segment.speaker;
      const existing = speakerTimelineSegmentsMap.get(speaker) || [];
      const overlaps = existing.some((entry) => {
        const overlap = Math.max(0, Math.min(entry.end, segment.end) - Math.max(entry.start, segment.start));
        return overlap > 0;
      });

      if (!overlaps) {
        const dominantEmotion = getDominantEmotionForRange(segment.start, segment.end, prosodySegments);
        const entry = {
          start: segment.start,
          end: segment.end,
          topEmotion: dominantEmotion?.name || null,
          score: typeof dominantEmotion?.score === 'number' ? dominantEmotion.score : null,
          text: segment.text || ''
        };

        speakerTimelineSegmentsMap.get(speaker).push(entry);
        latestTime = Math.max(latestTime, segment.end);
      }
    });
  }

  const speakerTimelineSpeakers = [];
  baseSpeakers.forEach((speaker) => {
    speakerTimelineSpeakers.push(speaker);
    if (!speakerTimelineSegmentsMap.has(speaker)) {
      speakerTimelineSegmentsMap.set(speaker, []);
    }
  });

  speakerTimelineSegmentsMap.forEach((segments, speaker) => {
    segments.sort((a, b) => a.start - b.start);
    if (!baseSpeakers.includes(speaker)) {
      if (speaker !== 'Unknown' && segments.length > 0) {
        speakerTimelineSpeakers.push(speaker);
      }
    }
  });

  const speakerTimelineSegments = {};
  speakerTimelineSpeakers.forEach((speaker) => {
    speakerTimelineSegments[speaker] = speakerTimelineSegmentsMap.get(speaker) || [];
  });

  return {
    chartData,
    emotions: emotionsList,
    speakerTimeline: {
      duration: latestTime,
      speakers: speakerTimelineSpeakers,
      segments: speakerTimelineSegments
    }
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

