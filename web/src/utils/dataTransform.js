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
      },
      categorizedEmotions: {
        positive: [],
        neutral: [],
        negative: [],
      },
      categoryCounts: {
        positive: 0,
        neutral: 0,
        negative: 0,
      },
      transcriptSegments: [],
    };
  }

  // Collect all unique emotions across segments
  const allEmotions = new Set();
  const transcriptSegments = buildTranscriptSegments(results?.metadata);
  const baseSpeakers = ['Customer', 'Agent'];
  const speakerSegmentsMap = new Map();
  baseSpeakers.forEach((speaker) => speakerSegmentsMap.set(speaker, []));

  let latestTime = 0;

  const categoryEmotionMap = {
    positive: new Map(),
    neutral: new Map(),
    negative: new Map(),
  };
  const categoryCounts = {
    positive: 0,
    neutral: 0,
    negative: 0,
  };

  const normalizeCategory = (value) => {
    if (!value) {
      return 'neutral';
    }
    const normalized = String(value).trim().toLowerCase();
    if (normalized === 'positive' || normalized === 'neutral' || normalized === 'negative') {
      return normalized;
    }
    return 'neutral';
  };

  const recordEmotion = (categoryKey, emotionName, score) => {
    const normalizedCategory = normalizeCategory(categoryKey);
    const bucket = categoryEmotionMap[normalizedCategory] || categoryEmotionMap.neutral;
    const existing = bucket.get(emotionName) || { count: 0, maxScore: 0, maxPercentage: 0, source: 'prosody' };
    existing.count += 1;
    if (typeof score === 'number') {
      existing.maxScore = Math.max(existing.maxScore, score);
      existing.maxPercentage = Math.max(existing.maxPercentage ?? 0, score * 100);
    }
    bucket.set(emotionName, existing);
  };

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
    const primaryCategory = normalizeCategory(
      segment.primary_category
      || dominantEmotion?.category
      || emotionList[0]?.category
      || 'neutral'
    );

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
      category: primaryCategory,
      speaker,
      text: segment.transcript_text || segment.text || ''
    });

    categoryCounts[primaryCategory] = (categoryCounts[primaryCategory] ?? 0) + 1;

    emotionList.forEach((emotion) => {
      const categoryKey = normalizeCategory(emotion.category || primaryCategory || 'neutral');
      recordEmotion(categoryKey, emotion.name, emotion.score);
    });

    if (!speakerSegmentsMap.has(speaker)) {
      speakerSegmentsMap.set(speaker, []);
    }

    speakerSegmentsMap.get(speaker).push({
      start: timeStart,
      end: timeEnd,
      topEmotion: dominantEmotion?.name || null,
      score: typeof dominantEmotion?.score === 'number' ? dominantEmotion.score : null,
      category: primaryCategory,
      text: segment.transcript_text || segment.text || ''
    });
  });

  if (Array.isArray(results.burst)) {
    results.burst.forEach((segment) => {
      const timeStart = typeof segment.time_start === 'number' ? segment.time_start : null;
      const timeEnd = typeof segment.time_end === 'number' ? segment.time_end : timeStart;
      if (timeStart === null || timeEnd === null || Number.isNaN(timeStart) || Number.isNaN(timeEnd)) {
        return;
      }

      const emotionList = Array.isArray(segment.top_emotions)
        ? segment.top_emotions.filter((emotion) => emotion?.name && typeof emotion.score === 'number')
        : [];

      emotionList.forEach((emotion) => {
        const categoryKey = normalizeCategory(emotion.category || segment.primary_category || 'neutral');
        const bucket = categoryEmotionMap[categoryKey] || categoryEmotionMap.neutral;
        const existing = bucket.get(emotion.name) || { count: 0, maxScore: 0, maxPercentage: 0, source: 'prosody' };
        existing.count += 0; // don't increment count for bursts
        if (typeof emotion.score === 'number') {
          existing.maxScore = Math.max(existing.maxScore, emotion.score);
          existing.maxPercentage = Math.max(existing.maxPercentage ?? 0, emotion.score * 100);
        }
        existing.source = 'burst';
        bucket.set(emotion.name, existing);
      });
    });
  }

  const emotionsList = Array.from(allEmotions).sort();

  const chartData = prosodySegments
    .map((segment) => {
      const duration = Math.max(0, (segment.end ?? segment.start) - segment.start);
      const midpoint = segment.start + (duration / 2);

      const emotionScores = {};
      segment.emotions.forEach((emotion) => {
        if (emotion?.name && typeof emotion.score === 'number') {
          emotionScores[emotion.name] = emotion.score;
        }
      });

      return {
        time: midpoint,
        intervalStart: segment.start,
        intervalEnd: segment.end,
        duration,
        topEmotion: segment.dominantEmotion?.name || null,
        score: typeof segment.dominantEmotion?.score === 'number' ? segment.dominantEmotion.score : 0,
        emotions: emotionScores,
        speaker: segment.speaker || null,
        category: segment.category || 'neutral',
      };
    })
    .sort((a, b) => a.intervalStart - b.intervalStart);

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
          category: normalizeCategory(dominantEmotion?.category || 'neutral'),
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

  if (results?.metadata?.category_counts) {
    Object.entries(results.metadata.category_counts).forEach(([key, value]) => {
      if (categoryCounts[key] !== undefined && typeof value === 'number') {
        // Retain existing counts from prosody; metadata counts include burst segments.
      }
    });
  }

  const categorizedEmotions = Object.fromEntries(
    Object.entries(categoryEmotionMap).map(([category, map]) => {
      const items = Array.from(map.entries()).map(([name, info]) => ({
        name,
        count: info.count,
        maxScore: info.maxScore ?? 0,
        percentage: info.maxPercentage ?? (info.maxScore ?? 0) * 100,
        source: info.source || 'prosody',
      })).filter((emotion) => emotion.count > 0);
      items.sort((a, b) => {
        if (b.count !== a.count) {
          return b.count - a.count;
        }
        return b.maxScore - a.maxScore;
      });
      return [category, items];
    })
  );

  return {
    chartData,
    emotions: emotionsList,
    speakerTimeline: {
      duration: latestTime,
      speakers: speakerTimelineSpeakers,
      segments: speakerTimelineSegments
    },
    categorizedEmotions,
    categoryCounts,
    transcriptSegments,
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

