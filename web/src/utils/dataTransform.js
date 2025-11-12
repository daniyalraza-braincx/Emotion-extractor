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

const TIMELINE_PARTS = [
  { id: 'start', label: 'Start' },
  { id: 'mid', label: 'Mid' },
  { id: 'end', label: 'End' },
];

function buildEmptyEmotionTimeline() {
  const emptyParts = TIMELINE_PARTS.map((part) => ({
    id: part.id,
    label: part.label,
    start: 0,
    end: 0,
    duration: 0,
    category: null,
    emotion: null,
    hasData: false,
  }));

  return {
    combined: emptyParts.map((part) => ({ ...part })),
    agent: emptyParts.map((part) => ({ ...part })),
    customer: emptyParts.map((part) => ({ ...part })),
  };
}

function createTimelineRanges(totalDuration) {
  const safeDuration = Number.isFinite(totalDuration) && totalDuration > 0 ? totalDuration : 0;

  if (safeDuration === 0) {
    return TIMELINE_PARTS.map((part) => ({
      ...part,
      start: 0,
      end: 0,
      duration: 0,
    }));
  }

  const third = safeDuration / 3;
  const startEnd = third;
  const midStart = third;
  const midEnd = Math.min(third * 2, safeDuration);
  const endStart = Math.min(third * 2, safeDuration);

  return [
    {
      id: 'start',
      label: 'Start',
      start: 0,
      end: startEnd,
      duration: Math.max(0, startEnd),
    },
    {
      id: 'mid',
      label: 'Mid',
      start: midStart,
      end: midEnd,
      duration: Math.max(0, midEnd - midStart),
    },
    {
      id: 'end',
      label: 'End',
      start: endStart,
      end: safeDuration,
      duration: Math.max(0, safeDuration - endStart),
    },
  ];
}

function normalizeSpeakerSegments(segments) {
  if (!Array.isArray(segments) || segments.length === 0) {
    return [];
  }

  return segments
    .map((segment) => {
      const segmentStart = Number(segment?.start);
      const segmentEndCandidate = Number(segment?.end ?? segment?.start);

      if (
        Number.isNaN(segmentStart)
        || Number.isNaN(segmentEndCandidate)
        || !Number.isFinite(segmentStart)
        || !Number.isFinite(segmentEndCandidate)
      ) {
        return null;
      }

      const segmentEnd = Math.max(segmentEndCandidate, segmentStart);
      return {
        ...segment,
        start: segmentStart,
        end: segmentEnd,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.start - b.start);
}

function accumulateSpeakerDuration(segments) {
  return segments.reduce((total, segment) => {
    const duration = Math.max(0, (segment.end ?? segment.start) - segment.start);
    return total + duration;
  }, 0);
}

function findSpeakerTimeAtDuration(segments, targetDuration, defaultValue) {
  if (!Array.isArray(segments) || segments.length === 0) {
    return defaultValue;
  }

  const clampedTarget = Math.max(0, targetDuration);
  let accumulated = 0;

  for (let index = 0; index < segments.length; index += 1) {
    const segment = segments[index];
    const duration = Math.max(0, (segment.end ?? segment.start) - segment.start);

    if (duration <= 0) {
      continue;
    }

    if (clampedTarget <= accumulated + duration) {
      const offset = clampedTarget - accumulated;
      return segment.start + offset;
    }

    accumulated += duration;
  }

  return segments[segments.length - 1].end;
}

function cloneRanges(ranges) {
  return TIMELINE_PARTS.map((part) => {
    const existing = ranges.find((range) => range.id === part.id);
    if (!existing) {
      return {
        id: part.id,
        label: part.label,
        start: 0,
        end: 0,
        duration: 0,
      };
    }
    return {
      id: existing.id,
      label: existing.label,
      start: existing.start,
      end: existing.end,
      duration: Math.max(0, existing.end - existing.start),
    };
  });
}

function createSpeakerTimelineRanges(segments, fallbackRanges) {
  const normalizedSegments = normalizeSpeakerSegments(segments);
  if (normalizedSegments.length === 0) {
    return cloneRanges(fallbackRanges);
  }

  const totalDuration = accumulateSpeakerDuration(normalizedSegments);
  if (!Number.isFinite(totalDuration) || totalDuration <= 0) {
    return cloneRanges(fallbackRanges);
  }

  const oneThird = totalDuration / 3;
  const twoThirds = oneThird * 2;
  const checkpoints = [0, oneThird, twoThirds, totalDuration];

  const boundaryTimes = checkpoints.map((checkpoint, index) => {
    if (index === 0) {
      return normalizedSegments[0].start;
    }
    if (index === checkpoints.length - 1) {
      return normalizedSegments[normalizedSegments.length - 1].end;
    }
    return findSpeakerTimeAtDuration(normalizedSegments, checkpoint, normalizedSegments[0].start);
  });

  return TIMELINE_PARTS.map((part, index) => {
    const start = boundaryTimes[index];
    const end = boundaryTimes[index + 1];
    const safeStart = Number.isFinite(start) ? start : 0;
    const safeEnd = Number.isFinite(end) ? end : safeStart;
    return {
      id: part.id,
      label: part.label,
      start: safeStart,
      end: Math.max(safeEnd, safeStart),
      duration: Math.max(0, Math.max(safeEnd, safeStart) - safeStart),
    };
  });
}

function computeDominantEmotionForWindow(rangeStart, rangeEnd, segments) {
  if (!Array.isArray(segments) || segments.length === 0) {
    return null;
  }

  if (!Number.isFinite(rangeStart) || !Number.isFinite(rangeEnd) || rangeEnd <= rangeStart) {
    return null;
  }

  let best = null;

  segments.forEach((segment) => {
    const segmentStart = Number(segment?.start);
    const segmentEnd = Number(segment?.end ?? segment?.start);

    if (
      Number.isNaN(segmentStart)
      || Number.isNaN(segmentEnd)
      || !Number.isFinite(segmentStart)
      || !Number.isFinite(segmentEnd)
    ) {
      return;
    }

    const overlap = Math.max(0, Math.min(rangeEnd, segmentEnd) - Math.max(rangeStart, segmentStart));
    if (overlap <= 0) {
      return;
    }

    const dominantEmotion = segment?.dominantEmotion && typeof segment.dominantEmotion === 'object'
      ? segment.dominantEmotion
      : null;
    const fallbackEmotion = Array.isArray(segment?.emotions) && segment.emotions.length > 0
      ? segment.emotions[0]
      : null;
    const emotionCandidate = dominantEmotion?.name ? dominantEmotion : (fallbackEmotion?.name ? fallbackEmotion : null);

    if (!emotionCandidate) {
      return;
    }

    const rawScore = typeof emotionCandidate.score === 'number' && Number.isFinite(emotionCandidate.score)
      ? emotionCandidate.score
      : null;
    const weightScore = rawScore !== null ? Math.max(rawScore, 0) : 1;
    const weight = overlap * (weightScore > 0 ? weightScore : Number.EPSILON);

    if (!best || weight > best.weight) {
      best = {
        weight,
        name: emotionCandidate.name || null,
        score: rawScore,
        category: normalizeSentimentCategory(
          segment?.category
          || emotionCandidate?.category
          || (segment?.emotions?.[0]?.category)
          || 'neutral',
        ),
      };
    }
  });

  if (!best) {
    return null;
  }

  const percentage = typeof best.score === 'number' && Number.isFinite(best.score)
    ? best.score * 100
    : null;

  return {
    name: best.name,
    score: best.score,
    percentage: Number.isFinite(percentage) ? Number(percentage.toFixed(1)) : null,
    category: best.category,
  };
}

function buildEmotionTimeline(prosodySegments, totalDurationSeconds) {
  if (!Array.isArray(prosodySegments) || prosodySegments.length === 0) {
    return buildEmptyEmotionTimeline();
  }

  const combinedRanges = createTimelineRanges(totalDurationSeconds);
  const segmentGroups = {
    combined: prosodySegments,
    agent: prosodySegments.filter((segment) => segment?.speaker === 'Agent'),
    customer: prosodySegments.filter((segment) => segment?.speaker === 'Customer'),
  };

  const rangeGroups = {
    combined: combinedRanges,
    agent: createSpeakerTimelineRanges(
      segmentGroups.agent,
      combinedRanges,
    ),
    customer: createSpeakerTimelineRanges(
      segmentGroups.customer,
      combinedRanges,
    ),
  };

  return Object.entries(segmentGroups).reduce((acc, [key, segments]) => {
    const targetRanges = rangeGroups[key] ? cloneRanges(rangeGroups[key]) : cloneRanges(combinedRanges);
    acc[key] = targetRanges.map((range) => {
      const dominant = computeDominantEmotionForWindow(range.start, range.end, segments);
      return {
        id: range.id,
        label: range.label,
        start: range.start,
        end: range.end,
        duration: Math.max(0, range.end - range.start),
        category: dominant?.category ?? null,
        emotion: dominant
          ? {
            name: dominant.name,
            score: dominant.score,
            percentage: dominant.percentage,
            category: dominant.category,
          }
          : null,
        hasData: Boolean(dominant),
      };
    });
    return acc;
  }, {
    combined: [],
    agent: [],
    customer: [],
  });
}

const SENTIMENT_KEYS = ['positive', 'neutral', 'negative'];

function normalizeSentimentCategory(value) {
  if (!value) {
    return 'neutral';
  }
  const normalized = String(value).trim().toLowerCase();
  if (normalized === 'positive' || normalized === 'neutral' || normalized === 'negative') {
    return normalized;
  }
  return 'neutral';
}

function createMetricAccumulator() {
  return {
    totalSegments: 0,
    categoryCounts: {
      positive: 0,
      neutral: 0,
      negative: 0,
    },
    categoryEmotionMap: {
      positive: new Map(),
      neutral: new Map(),
      negative: new Map(),
    },
  };
}

function cloneCategoryCounts(counts) {
  return {
    positive: counts.positive ?? 0,
    neutral: counts.neutral ?? 0,
    negative: counts.negative ?? 0,
  };
}

function convertEmotionBucket(bucketMap) {
  return Array.from(bucketMap.entries())
    .map(([name, info]) => ({
      name,
      count: info.count ?? 0,
      maxScore: info.maxScore ?? 0,
      percentage: info.maxPercentage ?? info.percentage ?? 0,
      source: info.source || 'prosody',
    }))
    .filter((emotion) => emotion.count > 0)
    .sort((a, b) => {
      if (b.count !== a.count) {
        return b.count - a.count;
      }
      return (b.maxScore ?? 0) - (a.maxScore ?? 0);
    });
}

const SENTIMENT_PRIORITY = ['positive', 'neutral', 'negative'];

function selectDominantCategory(counts = {}, categorizedEmotions = {}) {
  const categories = SENTIMENT_KEYS.map((category) => {
    const count = Number.isFinite(counts[category]) ? counts[category] : 0;
    const topEmotion = Array.isArray(categorizedEmotions?.[category])
      ? categorizedEmotions[category][0]
      : null;
    const strength = Number.isFinite(topEmotion?.maxScore)
      ? topEmotion.maxScore
      : (Number.isFinite(topEmotion?.percentage) ? topEmotion.percentage / 100 : 0);
    return { category, count, strength };
  });

  categories.sort((a, b) => {
    if (b.count !== a.count) {
      return b.count - a.count;
    }

    if (b.strength !== a.strength) {
      return b.strength - a.strength;
    }

    return SENTIMENT_PRIORITY.indexOf(a.category) - SENTIMENT_PRIORITY.indexOf(b.category);
  });

  const best = categories[0] || { category: 'neutral', count: 0 };
  return { category: best.category, count: best.count };
}

function deriveOverallEmotionFromMetrics(metrics, speakerLabel, fallbackOverallEmotion = null) {
  if (!metrics || typeof metrics !== 'object') {
    return null;
  }

  const totalSegments = Number.isFinite(metrics.segmentCount) ? metrics.segmentCount : 0;
  if (totalSegments <= 0) {
    return null;
  }

  const counts = metrics.categoryCounts || {};
  const categorizedEmotions = metrics.categorizedEmotions || {};
  const { category: dominantCategory, count: dominantCount } = selectDominantCategory(counts, categorizedEmotions);
  const dominantEmotions = categorizedEmotions[dominantCategory] || [];
  const topEmotion = dominantEmotions.length > 0 ? dominantEmotions[0] : null;

  const confidenceRatio = totalSegments > 0 ? dominantCount / totalSegments : 0;
  const confidence = Number(Math.min(Math.max(confidenceRatio, 0), 1).toFixed(3));

  const prettyCategory = dominantCategory.charAt(0).toUpperCase() + dominantCategory.slice(1);
  const ratioPercent = Math.round(confidenceRatio * 100);

  const reasoningParts = [
    `${speakerLabel} segments were mostly ${prettyCategory.toLowerCase()} (${dominantCount}/${totalSegments}).`,
  ];

  if (topEmotion?.name) {
    const peakPercentage = Number.isFinite(topEmotion.percentage)
      ? Math.round(topEmotion.percentage)
      : (Number.isFinite(topEmotion.maxScore) ? Math.round(topEmotion.maxScore * 100) : null);
    const emotionDetails = peakPercentage !== null
      ? `${topEmotion.name} peaked at ${peakPercentage}%`
      : topEmotion.name;
    reasoningParts.push(`Top emotion ${emotionDetails}.`);
  }

  if (dominantCount < totalSegments) {
    const residualCount = totalSegments - dominantCount;
    const residualPercent = Math.max(0, 100 - ratioPercent);
    reasoningParts.push(`${residualCount} segment${residualCount === 1 ? '' : 's'} showed other sentiments (${residualPercent}%).`);
  }

  const reasoning = reasoningParts.join(' ');

  return {
    label: dominantCategory,
    call_outcome: fallbackOverallEmotion?.call_outcome ?? null,
    confidence,
    reasoning,
    source: 'metrics',
  };
}

function materializeAccumulator(accumulator) {
  const categorizedEmotions = Object.fromEntries(
    SENTIMENT_KEYS.map((categoryKey) => [
      categoryKey,
      convertEmotionBucket(accumulator.categoryEmotionMap[categoryKey]),
    ]),
  );

  return {
    categoryCounts: cloneCategoryCounts(accumulator.categoryCounts),
    categorizedEmotions,
    overallEmotion: null,
    segmentCount: accumulator.totalSegments,
  };
}

function updateEmotionStat(accumulator, categoryKey, emotion, { incrementCount, source }) {
  const targetCategory = accumulator.categoryEmotionMap[categoryKey] || accumulator.categoryEmotionMap.neutral;
  const existing = targetCategory.get(emotion.name) || {
    count: 0,
    maxScore: 0,
    maxPercentage: 0,
    source,
  };

  if (incrementCount) {
    existing.count += 1;
  }

  if (typeof emotion.score === 'number') {
    existing.maxScore = Math.max(existing.maxScore ?? 0, emotion.score);
    const percentage = emotion.score * 100;
    existing.maxPercentage = Math.max(existing.maxPercentage ?? 0, percentage);
  }

  existing.source = source || existing.source;
  targetCategory.set(emotion.name, existing);
}

function mergeSegmentIntoAccumulator(
  accumulator,
  primaryCategory,
  emotionList,
  { source = 'prosody', incrementCounts = true } = {},
) {
  if (!accumulator) {
    return;
  }

  if (incrementCounts) {
    accumulator.totalSegments += 1;
    accumulator.categoryCounts[primaryCategory] = (accumulator.categoryCounts[primaryCategory] ?? 0) + 1;
  }

  emotionList.forEach((emotion) => {
    const emotionCategory = normalizeSentimentCategory(
      emotion.category || primaryCategory || 'neutral',
    );
    updateEmotionStat(accumulator, emotionCategory, emotion, {
      incrementCount: incrementCounts,
      source,
    });
  });
}

function getAccumulatorKeyForSpeaker(speaker) {
  if (!speaker) {
    return 'unknown';
  }

  const normalized = speaker.toLowerCase();
  if (normalized === 'agent') {
    return 'agent';
  }
  if (normalized === 'customer' || normalized === 'user') {
    return 'customer';
  }
  return 'unknown';
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
      emotionTimeline: buildEmptyEmotionTimeline(),
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
      overallEmotion: null,
      speakerMetrics: {
        combined: materializeAccumulator(createMetricAccumulator()),
        agent: materializeAccumulator(createMetricAccumulator()),
        customer: materializeAccumulator(createMetricAccumulator()),
      },
    };
  }

  // Collect all unique emotions across segments
  const allEmotions = new Set();
  const transcriptSegments = buildTranscriptSegments(results?.metadata);
  const baseSpeakers = ['Customer', 'Agent'];
  const speakerSegmentsMap = new Map();
  baseSpeakers.forEach((speaker) => speakerSegmentsMap.set(speaker, []));

  let latestTime = 0;

  const metricsAccumulators = {
    combined: createMetricAccumulator(),
    agent: createMetricAccumulator(),
    customer: createMetricAccumulator(),
    unknown: createMetricAccumulator(),
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
    const primaryCategory = normalizeSentimentCategory(
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

    mergeSegmentIntoAccumulator(metricsAccumulators.combined, primaryCategory, emotionList);
    const accumulatorKey = getAccumulatorKeyForSpeaker(speaker);
    mergeSegmentIntoAccumulator(metricsAccumulators[accumulatorKey], primaryCategory, emotionList);

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

      const normalizedSpeaker = normalizeSpeakerName(segment.speaker);
      const accumulatorKey = getAccumulatorKeyForSpeaker(normalizedSpeaker || segment.speaker);

      emotionList.forEach((emotion) => {
        const categoryKey = normalizeSentimentCategory(emotion.category || segment.primary_category || 'neutral');
        updateEmotionStat(metricsAccumulators.combined, categoryKey, emotion, {
          incrementCount: false,
          source: 'burst',
        });
        const targetAccumulator = metricsAccumulators[accumulatorKey];
        if (targetAccumulator) {
          updateEmotionStat(targetAccumulator, categoryKey, emotion, {
            incrementCount: false,
            source: 'burst',
          });
        }
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
          category: normalizeSentimentCategory(dominantEmotion?.category || 'neutral'),
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

  const emotionTimeline = buildEmotionTimeline(prosodySegments, latestTime);

  const combinedMetrics = materializeAccumulator(metricsAccumulators.combined);
  const speakerMetrics = {
    combined: combinedMetrics,
    agent: materializeAccumulator(metricsAccumulators.agent),
    customer: materializeAccumulator(metricsAccumulators.customer),
  };

  const overallEmotion = (() => {
    if (results?.metadata && typeof results.metadata === 'object') {
      const overall = results.metadata.overall_call_emotion || results.metadata.overallEmotion;
      if (overall) {
        return { ...overall };
      }
    }
    if (results?.overall_call_emotion) {
      return { ...results.overall_call_emotion };
    }
    return null;
  })();

  speakerMetrics.combined.overallEmotion = overallEmotion;
  speakerMetrics.agent.overallEmotion = deriveOverallEmotionFromMetrics(
    speakerMetrics.agent,
    'Agent',
    overallEmotion,
  );
  speakerMetrics.customer.overallEmotion = deriveOverallEmotionFromMetrics(
    speakerMetrics.customer,
    'Customer',
    overallEmotion,
  );

  return {
    chartData,
    emotions: emotionsList,
    speakerTimeline: {
      duration: latestTime,
      speakers: speakerTimelineSpeakers,
      segments: speakerTimelineSegments
    },
    emotionTimeline,
    categorizedEmotions: combinedMetrics.categorizedEmotions,
    categoryCounts: combinedMetrics.categoryCounts,
    transcriptSegments,
    overallEmotion,
    speakerMetrics,
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

