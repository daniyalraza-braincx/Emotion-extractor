import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  Cell,
  LabelList,
  ResponsiveContainer,
} from 'recharts';
import { analyzeAudioFile, analyzeRetellCall, getRetellCallAnalysis } from '../services/api';
import { transformApiDataToChart } from '../utils/dataTransform';
import { formatTimestamp, formatDuration, formatStatusLabel } from '../utils/formatters';
import { useAnalysis } from '../context/AnalysisContext';

const CATEGORY_COLORS = Object.freeze({
  positive: '#63d3ad',
  neutral: '#f5d37b',
  negative: '#f17878',
});
const SPEAKER_COLORS = Object.freeze({
  Customer: '#2563eb',
  Agent: '#a855f7',
  Unknown: '#94a3b8',
});
const SPEAKER_ICONS = Object.freeze({
  Customer: '🧑',
  Agent: '🤖',
  Unknown: '❔',
});

const EMPTY_CATEGORY_COUNTS = Object.freeze({
  positive: 0,
  neutral: 0,
  negative: 0,
});

function createEmptyMetricSummary() {
  return {
    categoryCounts: { ...EMPTY_CATEGORY_COUNTS },
    categorizedEmotions: {
      positive: [],
      neutral: [],
      negative: [],
    },
    overallEmotion: null,
    segmentCount: 0,
  };
}

function createEmptySpeakerMetrics() {
  return {
    combined: createEmptyMetricSummary(),
    agent: createEmptyMetricSummary(),
    customer: createEmptyMetricSummary(),
  };
}
import humanAvatar from '../assets/human.png';
import agentAvatar from '../assets/agent.png';

function CustomTooltip({ active, payload, emotionColorMap }) {
  if (!active || !payload || payload.length === 0) {
    return null;
  }

  const tooltipData = payload[0]?.payload;
  if (!tooltipData) {
    return null;
  }

  const {
    intervalStart,
    intervalEnd,
    topEmotion,
    score,
  } = tooltipData;
  const hasTopEmotion = topEmotion && typeof score === 'number';
  const color = hasTopEmotion ? (emotionColorMap?.[topEmotion] || '#ffffff') : '#ffffff';

  return (
    <div>
      <p style={{ margin: 0, color: '#ffffff', fontWeight: 600 }}>
        {`${intervalStart}s - ${intervalEnd}s`}
      </p>
      {hasTopEmotion ? (
        <p
          style={{
            margin: 0,
            marginTop: 4,
            color,
            fontWeight: 500,
          }}
        >
          {`${topEmotion} : ${score.toFixed(4)}`}
        </p>
      ) : (
        <p style={{ margin: 0, marginTop: 4, color: '#ffffff' }}>No detected emotion</p>
      )}
    </div>
  );
}

function SegmentBarShape(props) {
  const {
    payload,
    fill,
    x,
    y,
    height,
    width,
    averageDuration,
  } = props;

  if (!payload) {
    return null;
  }

  const { intervalStart, intervalEnd, score } = payload;
  const baseX = Number.isFinite(x) ? x : 0;
  const baseWidth = Number.isFinite(width) ? width : 0;

  const duration = Number.isFinite(intervalEnd) && Number.isFinite(intervalStart)
    ? Math.max(0, intervalEnd - intervalStart)
    : 0;

  const durationToPixelScale = (() => {
    const reference = Number.isFinite(averageDuration) && averageDuration > 0 ? averageDuration : 1;
    const base = baseWidth > 0 ? baseWidth : 12;
    return base / reference;
  })();

  const computedWidth = Math.max(8, duration * durationToPixelScale);
  const centerX = baseX + (baseWidth / 2);
  const computedX = centerX - (computedWidth / 2);

  return (
    <rect
      x={Number.isFinite(computedX) ? computedX : baseX}
      y={Number.isFinite(y) ? y : 0}
      width={Number.isFinite(computedWidth) ? computedWidth : baseWidth || 8}
      height={Number.isFinite(height) ? height : 8}
      fill={fill || '#888888'}
      rx={4}
      ry={4}
    />
  );
}

function SpeakerLabel(props) {
  const {
    x,
    y,
    width,
    value,
  } = props;

  if (!value) {
    return null;
  }

  const baseX = Number.isFinite(x) ? x : 0;
  const baseY = Number.isFinite(y) ? y : 0;
  const barWidth = Number.isFinite(width) ? width : 0;
  const textX = baseX + (barWidth / 2);
  const textY = baseY - 6;
  const icon = SPEAKER_ICONS[value] || SPEAKER_ICONS.Unknown;

  return (
    <text
      x={textX}
      y={textY}
      fill="#1f2937"
      fontSize={16}
      textAnchor="middle"
    >
      {icon}
    </text>
  );
}

function createEmptyTimeline() {
  return {
    duration: 0,
    speakers: [],
    segments: {}
  };
}

function normalizeTimeline(timeline) {
  if (!timeline || typeof timeline !== 'object') {
    return createEmptyTimeline();
  }

  const duration = (typeof timeline.duration === 'number' && Number.isFinite(timeline.duration) && timeline.duration > 0)
    ? timeline.duration
    : 0;

  const segmentEntries = (timeline.segments && typeof timeline.segments === 'object')
    ? Object.entries(timeline.segments)
    : [];

  const baseSpeakers = ['Customer', 'Agent'];
  const speakerOrder = [];
  const seenSpeakers = new Set();

  const candidateSpeakers = [
    ...baseSpeakers,
    ...(Array.isArray(timeline.speakers) ? timeline.speakers : []),
    ...segmentEntries.map(([speaker]) => speaker)
  ];

  candidateSpeakers.forEach((speaker) => {
    if (!speaker || seenSpeakers.has(speaker)) {
      return;
    }
    seenSpeakers.add(speaker);
    speakerOrder.push(speaker);
  });

  const segments = {};
  speakerOrder.forEach((speaker) => {
    const segmentList = Array.isArray(timeline.segments?.[speaker]) ? timeline.segments[speaker] : [];
    segments[speaker] = segmentList.map((segment) => {
      const start = (typeof segment.start === 'number' && Number.isFinite(segment.start)) ? segment.start : 0;
      const end = (typeof segment.end === 'number' && Number.isFinite(segment.end)) ? segment.end : start;
      return {
        start,
        end,
        topEmotion: segment.topEmotion || null,
        score: (typeof segment.score === 'number' && Number.isFinite(segment.score)) ? segment.score : null,
        text: segment.text || '',
        category: segment.category || (segment.topEmotionCategory ?? null) || null,
      };
    });
  });

  return {
    duration,
    speakers: speakerOrder,
    segments
  };
}

function SpeakerTimeline({
  timeline,
  currentTime,
  audioDuration,
  emotionColorMap,
  avatarMap = {},
  speakerColors = {},
  categoryColors = {},
  onSeek,
}) {
  if (!timeline) {
    return null;
  }

  const baseSpeakers = ['Customer', 'Agent'];
  const speakersToRender = baseSpeakers.map((speaker) => ({
    name: speaker,
    segments: Array.isArray(timeline.segments?.[speaker]) ? timeline.segments[speaker] : [],
  }));

  const rawDuration = typeof timeline.duration === 'number' && Number.isFinite(timeline.duration)
    ? timeline.duration
    : 0;
  const effectiveDuration = [rawDuration, audioDuration]
    .filter((value) => typeof value === 'number' && Number.isFinite(value) && value > 0)
    .reduce((max, value) => Math.max(max, value), 0);

  if (!(effectiveDuration > 0)) {
    return null;
  }

  const clampedProgress = Math.min(Math.max((currentTime / effectiveDuration) * 100, 0), 100);
  const clampedTime = Math.min(Math.max(currentTime, 0), effectiveDuration);

  const computeSeekTime = (clientX, element) => {
    if (!element || typeof clientX !== 'number') {
      return null;
    }
    const rect = element.getBoundingClientRect();
    if (!rect || rect.width <= 0) {
      return null;
    }
    const offset = clientX - rect.left;
    const ratio = Math.min(Math.max(offset / rect.width, 0), 1);
    return ratio * effectiveDuration;
  };

  const handleTrackClick = (event) => {
    if (typeof onSeek !== 'function') {
      return;
    }
    const element = event.currentTarget;
    const nextTime = computeSeekTime(event.clientX, element);
    if (Number.isFinite(nextTime)) {
      onSeek(nextTime);
    }
  };

  const handleTrackTouch = (event) => {
    if (typeof onSeek !== 'function') {
      return;
    }
    const touch = event.touches && event.touches[0];
    if (!touch) {
      return;
    }
    event.preventDefault();
    const element = event.currentTarget;
    const nextTime = computeSeekTime(touch.clientX, element);
    if (Number.isFinite(nextTime)) {
      onSeek(nextTime);
    }
  };

  const handleTrackKeyDown = (event) => {
    if (typeof onSeek !== 'function') {
      return;
    }
    const step = effectiveDuration > 0 ? Math.max(effectiveDuration / 40, 0.5) : 1;
    if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
      event.preventDefault();
      onSeek(Math.min(clampedTime + step, effectiveDuration));
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
      event.preventDefault();
      onSeek(Math.max(clampedTime - step, 0));
    } else if (event.key === 'Home') {
      event.preventDefault();
      onSeek(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      onSeek(effectiveDuration);
    }
  };

  return (
    <div className="speaker-timeline">
      {speakersToRender.map(({ name, segments }) => {
        return (
          <div className="speaker-timeline-row" key={name}>
            <div className="speaker-timeline-label">
              {avatarMap[name] && (
                <span className="speaker-timeline-avatar">
                  <img src={avatarMap[name]} alt={`${name} avatar`} />
                </span>
              )}
              <span>{name}</span>
            </div>
            <div
              className="speaker-timeline-track"
              onClick={handleTrackClick}
              onTouchStart={handleTrackTouch}
              role={typeof onSeek === 'function' ? 'slider' : undefined}
              tabIndex={typeof onSeek === 'function' ? 0 : undefined}
              aria-valuemin={0}
              aria-valuemax={Math.round(effectiveDuration)}
              aria-valuenow={Math.round(clampedTime)}
              aria-valuetext={`${clampedTime.toFixed(2)} seconds`}
              aria-label={`Timeline for ${name}`}
              onKeyDown={handleTrackKeyDown}
            >
              {segments.map((segment, index) => {
                const segmentStart = typeof segment.start === 'number' ? segment.start : 0;
                const segmentEnd = typeof segment.end === 'number' ? segment.end : segmentStart;
                const widthPercent = Math.max(
                  ((segmentEnd - segmentStart) / effectiveDuration) * 100,
                  0.8
                );
                const leftPercent = Math.min(
                  Math.max((segmentStart / effectiveDuration) * 100, 0),
                  100
                );
                const categoryKey = typeof segment.category === 'string'
                  ? segment.category.toLowerCase()
                  : null;
                const categoryColor = categoryKey ? categoryColors?.[categoryKey] : undefined;
                const emotionColor = segment.topEmotion ? emotionColorMap?.[segment.topEmotion] : null;
                const color = categoryColor
                  || emotionColor
                  || speakerColors?.[name]
                  || '#ccd2f6';
                const titleParts = [
                  `${segmentStart.toFixed(2)}s - ${segmentEnd.toFixed(2)}s`,
                  segment.topEmotion ? `Emotion: ${segment.topEmotion}` : 'No detected emotion'
                ];
                if (segment.score) {
                  titleParts.push(`Score: ${segment.score.toFixed(4)}`);
                }
                if (segment.text) {
                  titleParts.push(`Transcript: ${segment.text}`);
                }

                return (
                  <div
                    key={`${name}-${index}-${segmentStart}`}
                    className="speaker-timeline-segment"
                    style={{
                      left: `${leftPercent}%`,
                      width: `${Math.min(widthPercent, 100 - leftPercent)}%`,
                      backgroundColor: color
                    }}
                    title={titleParts.join(' | ')}
                    aria-label={`${name} segment from ${segmentStart.toFixed(2)} seconds to ${segmentEnd.toFixed(2)} seconds`}
                  />
                );
              })}
              <div
                className="speaker-timeline-progress"
                style={{ left: `${clampedProgress}%` }}
                aria-hidden="true"
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function formatFileSize(bytes) {
  if (!Number.isFinite(bytes)) {
    return 'Unknown size';
  }
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${bytes} bytes`;
}

function formatClockTime(timeInSeconds) {
  if (!Number.isFinite(timeInSeconds) || timeInSeconds < 0) {
    return '0:00';
  }
  const minutes = Math.floor(timeInSeconds / 60);
  const seconds = Math.floor(timeInSeconds % 60)
    .toString()
    .padStart(2, '0');
  return `${minutes}:${seconds}`;
}

function formatSecondsCompact(value) {
  if (!Number.isFinite(value)) {
    return '0.00s';
  }
  return `${value.toFixed(2)}s`;
}

function AnalysisPage() {
  const navigate = useNavigate();
  const { analysisRequest } = useAnalysis();

  const audioRef = useRef(null);
  const [activeRequest, setActiveRequest] = useState(null);

  const [chartData, setChartData] = useState([]);
  const [emotions, setEmotions] = useState([]);
  const [summary, setSummary] = useState(null);
  const [categoryCounts, setCategoryCounts] = useState({ positive: 0, neutral: 0, negative: 0 });
  const [categorizedEmotions, setCategorizedEmotions] = useState({
    positive: [],
    neutral: [],
    negative: [],
  });
  const [overallEmotion, setOverallEmotion] = useState(null);
  const [speakerMetrics, setSpeakerMetrics] = useState(() => createEmptySpeakerMetrics());
  const [activeMetricsSpeaker, setActiveMetricsSpeaker] = useState('combined');
  const [timeline, setTimeline] = useState(() => createEmptyTimeline());
  const [transcriptSegments, setTranscriptSegments] = useState([]);
  const [errorInfo, setErrorInfo] = useState({ message: null, retryAllowed: true });
  const [isLoading, setIsLoading] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [activeTab, setActiveTab] = useState('overview');
  const [playbackRate, setPlaybackRate] = useState(1);

  const [audioSource, setAudioSource] = useState({ url: null, isObjectUrl: false });

  useEffect(() => () => {
    if (audioSource.isObjectUrl && audioSource.url) {
      URL.revokeObjectURL(audioSource.url);
    }
  }, [audioSource]);

  const emotionCategoryMap = useMemo(() => {
    const mapping = {};
    Object.entries(categorizedEmotions).forEach(([categoryKey, items]) => {
      if (!Array.isArray(items)) {
        return;
      }
      items.forEach((emotion) => {
        if (emotion?.name) {
          const normalized = String(categoryKey).trim().toLowerCase();
          mapping[emotion.name] = normalized;
        }
      });
    });
    chartData.forEach((entry) => {
      if (entry?.topEmotion) {
        const normalized = typeof entry.category === 'string'
          ? entry.category.trim().toLowerCase()
          : null;
        if (normalized) {
          mapping[entry.topEmotion] = normalized;
        }
      }
    });
    return mapping;
  }, [categorizedEmotions, chartData]);

  const emotionColorMap = useMemo(() => {
    const mapping = {};
    if (emotions.length === 0) {
      return mapping;
    }

    emotions.forEach((emotion) => {
      const categoryKey = typeof emotionCategoryMap[emotion] === 'string'
        ? emotionCategoryMap[emotion].toLowerCase()
        : null;
      const color = CATEGORY_COLORS[categoryKey] || CATEGORY_COLORS.neutral;
      mapping[emotion] = color;
    });

    return mapping;
  }, [emotions, emotionCategoryMap]);

  const intervalDuration = useMemo(() => {
    if (chartData.length === 0) return 10;
    const total = chartData.reduce((sum, entry) => {
      const delta = (entry.intervalEnd ?? entry.intervalStart) - entry.intervalStart;
      return sum + (Number.isFinite(delta) ? Math.max(0, delta) : 0);
    }, 0);
    const average = total / chartData.length;
    return Number.isFinite(average) && average > 0 ? average : 10;
  }, [chartData]);

  const intervalLookup = useMemo(() => {
    const map = new Map();
    chartData.forEach((entry) => {
      map.set(entry.time, entry);
    });
    return map;
  }, [chartData]);

  const sortedTranscriptSegments = useMemo(() => {
    if (!Array.isArray(transcriptSegments) || transcriptSegments.length === 0) {
      return [];
    }
    return transcriptSegments
      .filter((segment) => segment && Number.isFinite(segment.start))
      .slice()
      .sort((a, b) => (a.start ?? 0) - (b.start ?? 0));
  }, [transcriptSegments]);

  const updateAudioSource = useCallback((url, isObjectUrl = false) => {
    setAudioSource((previous) => {
      if (previous.isObjectUrl && previous.url) {
        URL.revokeObjectURL(previous.url);
      }
      return { url, isObjectUrl };
    });
  }, []);

  const resetVisualizationState = useCallback(() => {
    setChartData([]);
    setEmotions([]);
    setSummary(null);
    setOverallEmotion(null);
    setSpeakerMetrics(createEmptySpeakerMetrics());
    setActiveMetricsSpeaker('combined');
    setTimeline(createEmptyTimeline());
    setTranscriptSegments([]);
    setErrorInfo({ message: null, retryAllowed: true });
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);
  }, []);

const applyAnalysisResponse = useCallback((
  response,
  fallbackRecordingUrl = null,
  fallbackIsObjectUrl = false,
) => {
  const transformedPayload = transformApiDataToChart(response);
  const {
    chartData: transformed,
    emotions: detected,
    speakerTimeline,
    categorizedEmotions: categorized,
    categoryCounts: counts,
    transcriptSegments: transcriptList,
    overallEmotion: overall,
    speakerMetrics: metrics,
  } = transformedPayload;

  if (transformed.length === 0) {
    throw new Error('No emotion data found in the analysis results');
  }

  if (detected.length === 0) {
    throw new Error('No emotions detected in the audio');
  }

  setChartData(transformed);
  setEmotions(detected);
  setSummary(response.results.summary || null);
  setCategoryCounts(counts || { positive: 0, neutral: 0, negative: 0 });
  setCategorizedEmotions(categorized || { positive: [], neutral: [], negative: [] });
  setOverallEmotion(overall || null);
  const resolvedMetrics = metrics || createEmptySpeakerMetrics();
  setSpeakerMetrics(resolvedMetrics);
  setActiveMetricsSpeaker(() => {
    const combinedMetrics = resolvedMetrics.combined || createEmptyMetricSummary();
    return combinedMetrics.segmentCount > 0 ? 'combined' : 'combined';
  });
  setTimeline(normalizeTimeline(speakerTimeline));
  setTranscriptSegments(Array.isArray(transcriptList) ? transcriptList : []);

  if (response.recording_url) {
    updateAudioSource(response.recording_url, false);
  } else if (fallbackRecordingUrl) {
    updateAudioSource(fallbackRecordingUrl, fallbackIsObjectUrl);
  } else {
    updateAudioSource(null, false);
  }
}, [updateAudioSource]);

  const runAnalysis = useCallback(async (request, options = {}) => {
    if (!request) return;

    resetVisualizationState();
    setIsLoading(true);

    try {
      const forceAnalyze = Boolean(options.force);

      if (request.type === 'upload') {
        if (!request.file) {
          throw new Error('Audio file is missing from the analysis request.');
        }

        const objectUrl = URL.createObjectURL(request.file);
        const response = await analyzeAudioFile(request.file);
        if (!response.success || !response.results) {
          throw new Error('Invalid response from server');
        }

        await applyAnalysisResponse(response, objectUrl, true);

      } else if (request.type === 'retell') {
        const callId = request.call?.call_id;
        if (!callId) {
          throw new Error('Retell call_id is missing from the request.');
        }

        if (request.call?.analysis_allowed === false) {
          const reason = request.call?.analysis_block_reason || 'Call cannot be analyzed.';
          setErrorInfo({ message: reason, retryAllowed: false });
          return;
        }

        let response = null;
        if (!forceAnalyze) {
          try {
            response = await getRetellCallAnalysis(callId);
          } catch (storedError) {
            response = null;
          }
        }

        if (!response) {
          response = await analyzeRetellCall(callId, { force: forceAnalyze });
        }

        if (!response.success || !response.results) {
          throw new Error('Invalid response from server');
        }

        const fallbackRecording = request.call?.recording_multi_channel_url || null;
        await applyAnalysisResponse(response, fallbackRecording, false);
      } else {
        throw new Error('Unsupported analysis request type.');
      }
    } catch (err) {
      const message = err?.message || 'Failed to analyze audio. Please try again.';
      const retryAllowed = !/cannot be analyzed|cannot analyze emotions/i.test(message);
      setErrorInfo({ message, retryAllowed });
    } finally {
      setIsLoading(false);
    }
  }, [resetVisualizationState, applyAnalysisResponse]);

  useEffect(() => {
    if (!analysisRequest) {
      navigate('/', { replace: true });
      return;
    }

    setActiveRequest(analysisRequest);
    if (analysisRequest?.type === 'retell' && analysisRequest.call?.analysis_allowed === false) {
      const reason = analysisRequest.call.analysis_block_reason || 'Call cannot be analyzed.';
      setErrorInfo({ message: reason, retryAllowed: false });
    }
  }, [analysisRequest, navigate]);

  useEffect(() => {
    if (!activeRequest) {
      return;
    }

    runAnalysis(activeRequest);
  }, [activeRequest, runAnalysis]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !audioSource.url) {
      return () => {};
    }

    if (audio.readyState === 0) {
      audio.load();
    }

    const syncDuration = () => {
      if (!Number.isNaN(audio.duration) && audio.duration > 0 && Number.isFinite(audio.duration)) {
        setDuration(audio.duration);
      }
    };

    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);
    const handleEnded = () => {
      setIsPlaying(false);
      setCurrentTime(0);
      audio.currentTime = 0;
    };
    const handleTimeUpdate = (event) => {
      const element = event.target || audioRef.current;
      if (element && !Number.isNaN(element.currentTime) && Number.isFinite(element.currentTime)) {
        setCurrentTime(element.currentTime);
      }
    };

    audio.addEventListener('loadedmetadata', syncDuration);
    audio.addEventListener('loadeddata', syncDuration);
    audio.addEventListener('canplay', syncDuration);
    audio.addEventListener('play', handlePlay);
    audio.addEventListener('playing', handlePlay);
    audio.addEventListener('pause', handlePause);
    audio.addEventListener('ended', handleEnded);
    audio.addEventListener('timeupdate', handleTimeUpdate);

    const intervalId = setInterval(() => {
      if (!Number.isNaN(audio.currentTime)) {
        setCurrentTime(audio.currentTime);
      }
    }, 100);

    syncDuration();

    return () => {
      clearInterval(intervalId);
      audio.removeEventListener('loadedmetadata', syncDuration);
      audio.removeEventListener('loadeddata', syncDuration);
      audio.removeEventListener('canplay', syncDuration);
      audio.removeEventListener('play', handlePlay);
      audio.removeEventListener('playing', handlePlay);
      audio.removeEventListener('pause', handlePause);
      audio.removeEventListener('ended', handleEnded);
      audio.removeEventListener('timeupdate', handleTimeUpdate);
    };
  }, [audioSource]);

  useEffect(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.playbackRate = playbackRate;
    }
  }, [playbackRate]);

  const legendPayload = useMemo(() => (
    emotions.map((emotion) => ({
      value: emotion,
      type: 'square',
      color: emotionColorMap[emotion] || '#888888',
    }))
  ), [emotions, emotionColorMap]);

  const loadingMessage = activeRequest?.type === 'retell'
    ? 'Analyzing Retell call… This may take a moment.'
    : 'Analyzing audio file… This may take a moment.';

  const handleRetry = () => {
    if (activeRequest && canRetry) {
      const options = activeRequest.type === 'retell' ? { force: true } : {};
      runAnalysis(activeRequest, options);
    }
  };

  const handleBack = () => {
    navigate('/');
  };

  const analysisTitle = activeRequest?.type === 'retell'
    ? activeRequest?.call?.call_id || 'Retell Call'
    : activeRequest?.file?.name || 'Custom Audio';

  const callDuration = activeRequest?.type === 'retell'
    ? formatDuration(activeRequest.call?.start_timestamp, activeRequest.call?.end_timestamp)
    : null;

  const recordingUrl = audioSource.url && !audioSource.isObjectUrl ? audioSource.url : null;

  const analysisBadge = activeRequest?.type === 'retell' ? 'Retell Call' : 'Custom Upload';
  const isRetell = activeRequest?.type === 'retell';

  const avatarMap = useMemo(() => ({
    Customer: humanAvatar,
    Agent: agentAvatar,
  }), []);

  const speakerColors = useMemo(() => SPEAKER_COLORS, []);

  const metadataPills = useMemo(() => {
    const items = [];

    if (isRetell) {
      if (callDuration) {
        items.push({ id: 'duration', label: `Duration: ${callDuration}` });
      }
      if (activeRequest?.call?.start_timestamp) {
        items.push({ id: 'started', label: `Started: ${formatTimestamp(activeRequest.call.start_timestamp)}` });
      }
      if (activeRequest?.call?.end_timestamp) {
        items.push({ id: 'ended', label: `Ended: ${formatTimestamp(activeRequest.call.end_timestamp)}` });
      }
      if (activeRequest?.call?.last_updated) {
        items.push({ id: 'updated', label: `Updated: ${formatTimestamp(activeRequest.call.last_updated)}` });
      }
      if (activeRequest?.call?.agent_id) {
        items.push({ id: 'agent', label: `Agent: ${activeRequest.call.agent_id}` });
      }
      items.push({
        id: 'status',
        label: `Status: ${formatStatusLabel(activeRequest?.call?.analysis_status)}`,
      });
      items.push({
        id: 'analysis',
        label: activeRequest?.call?.analysis_available ? 'Analysis Ready' : 'Analysis Pending',
      });
      items.push({
        id: 'transcript',
        label: activeRequest?.call?.transcript_available ? 'Transcript Ready' : 'Transcript Pending',
      });
    } else if (activeRequest?.type === 'upload') {
      if (activeRequest.file?.size) {
        items.push({ id: 'size', label: `Size: ${formatFileSize(activeRequest.file.size)}` });
      }
      if (activeRequest.file?.type) {
        items.push({ id: 'type', label: `Type: ${activeRequest.file.type}` });
      }
      if (activeRequest.file?.lastModified) {
        items.push({
          id: 'modified',
          label: `Modified: ${new Date(activeRequest.file.lastModified).toLocaleString()}`,
        });
      }
    }

    return items;
  }, [isRetell, callDuration, activeRequest]);

  const summaryHeading = useMemo(() => {
    if (isRetell) {
      return 'Call Summary';
    }
    if (activeRequest?.type === 'upload') {
      return 'Analysis Summary';
    }
    return 'Analysis Summary';
  }, [isRetell, activeRequest]);

  const summaryBody = useMemo(() => {
    if (summary && typeof summary === 'string') {
      return summary.trim();
    }
    return isRetell
      ? 'Emotion insights for the selected Retell call.'
      : 'Emotion insights for your uploaded audio file.';
  }, [summary, isRetell]);

  const tabs = useMemo(() => ([
    { id: 'overview', label: 'Overview' },
    { id: 'transcript', label: 'Transcript' },
    { id: 'metrics', label: 'Metrics' },
    // { id: 'evaluations', label: 'Evaluations' },
  ]), []);

  const metricsOptions = useMemo(() => ([
    { id: 'combined', label: 'Combined' },
    { id: 'customer', label: 'User' },
    { id: 'agent', label: 'Agent' },
  ]), []);

  const activeSpeakerMetrics = useMemo(() => {
    const fallback = speakerMetrics?.combined ?? createEmptyMetricSummary();
    const selected = speakerMetrics?.[activeMetricsSpeaker] ?? fallback;
    const safeCounts = selected?.categoryCounts ?? { ...EMPTY_CATEGORY_COUNTS };
    const safeCategories = selected?.categorizedEmotions ?? {
      positive: [],
      neutral: [],
      negative: [],
    };

    return {
      categoryCounts: safeCounts,
      categorizedEmotions: safeCategories,
      overallEmotion: selected?.overallEmotion ?? null,
      segmentCount: selected?.segmentCount ?? 0,
    };
  }, [speakerMetrics, activeMetricsSpeaker]);

  const hasError = Boolean(errorInfo.message);
  const errorMessage = errorInfo.message;
  const canRetry = errorInfo.retryAllowed;

  const playDisabled = !audioSource.url;
  const formattedCurrentTime = formatClockTime(currentTime);
  const formattedDuration = formatClockTime(duration);
  const playbackOptions = [1, 1.25, 1.5, 2];

  const handleTimelineSeek = useCallback((nextTime) => {
    if (!Number.isFinite(nextTime)) {
      return;
    }
    const audio = audioRef.current;
    const audioDurationValue = audio && Number.isFinite(audio.duration) && audio.duration > 0
      ? audio.duration
      : (Number.isFinite(duration) && duration > 0 ? duration : null);
    const upperBound = audioDurationValue ?? nextTime;
    const targetTime = Math.max(0, Math.min(nextTime, upperBound));
    if (audio) {
      try {
        audio.currentTime = targetTime;
      } catch {
        // Ignore errors when adjusting playback on partially loaded audio
      }
    }
    setCurrentTime(targetTime);
  }, [duration]);

  const togglePlay = () => {
    if (playDisabled) {
      return;
    }
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    if (audio.paused) {
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  };

  const handlePlaybackRateChange = (event) => {
    const nextRate = Number(event.target.value);
    if (Number.isFinite(nextRate) && nextRate > 0) {
      setPlaybackRate(nextRate);
    }
  };

  const handleTabClick = (tabId) => {
    setActiveTab(tabId);
  };

  return (
    <main className="analysis-page">
      <header className="analysis-hero">
        <div className="analysis-hero__heading">
          <div className="analysis-hero__title-group">
            <button type="button" className="analysis-back-button" onClick={handleBack}>
              ← Back
          </button>
            <span className="analysis-badge">{analysisBadge}</span>
          <h1>{analysisTitle}</h1>
            </div>
          <div className="analysis-hero__actions">
            {recordingUrl && (
              <a
                className="analysis-action"
                href={recordingUrl}
                target="_blank"
                rel="noreferrer"
              >
                Download Audio
              </a>
            )}
          <button
            type="button"
              className="analysis-action analysis-action--primary"
            onClick={handleRetry}
            disabled={isLoading}
          >
            Re-run Analysis
          </button>
            <button
              type="button"
              className="analysis-action"
              onClick={handleBack}
            >
              Close
            </button>
        </div>
        </div>

        <div className="analysis-hero__media">
          <div className="analysis-playback">
            <div className="analysis-playback__header">
              <div className="analysis-playback__left">
                <button
                  type="button"
                  className={`play-toggle ${isPlaying ? 'is-playing' : ''}`}
                  onClick={togglePlay}
                  disabled={playDisabled}
                  aria-pressed={isPlaying}
                >
                  {isPlaying ? 'Pause' : 'Play'}
          </button>
                <span className="analysis-playback__timer">
                  {formattedCurrentTime} / {formattedDuration}
                </span>
        </div>
              <label className="analysis-playback__speed">
                Speed:
                <select
                  value={playbackRate}
                  onChange={handlePlaybackRateChange}
                  disabled={playDisabled}
                  aria-label="Playback speed"
                >
                  {playbackOptions.map((rate) => (
                    <option key={rate} value={rate}>
                      {`${rate}x`}
                    </option>
                  ))}
                </select>
              </label>
            </div>
              <audio
                ref={audioRef}
              src={audioSource.url || undefined}
                preload="metadata"
              className="analysis-audio-element"
              aria-hidden="true"
              />
            </div>

          <div className="analysis-hero__timeline">
            <SpeakerTimeline
              timeline={timeline}
              currentTime={currentTime}
              audioDuration={duration}
              emotionColorMap={emotionColorMap}
              avatarMap={avatarMap}
              speakerColors={speakerColors}
              categoryColors={CATEGORY_COLORS}
              onSeek={handleTimelineSeek}
            />
          </div>
        </div>
      </header>

      <nav className="analysis-tabs" role="tablist" aria-label="Analysis sections">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`analysis-tab ${activeTab === tab.id ? 'is-active' : ''}`}
            onClick={() => handleTabClick(tab.id)}
            role="tab"
            aria-selected={activeTab === tab.id}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {!isLoading && !hasError && (
        <section className="analysis-summary-panel">
          <div className="analysis-summary-panel__body">
            <h2>{summaryHeading}</h2>
            {summaryBody && <p>{summaryBody}</p>}
          </div>
          {metadataPills.length > 0 && (
            <div className="analysis-summary-meta">
              {metadataPills.map((pill) => (
                <span key={pill.id} className="analysis-chip">
                  {pill.label}
                </span>
              ))}
            </div>
          )}
        </section>
      )}

      <div className="analysis-content">
        {isLoading && (
          <div className="analysis-state-card">
            <div className="spinner" />
            <p>{loadingMessage}</p>
          </div>
        )}

        {!isLoading && hasError && (
          <div className="analysis-state-card analysis-state-card--error">
            <p className="error-message">{errorMessage}</p>
            <button
              className="retry-button"
              onClick={handleRetry}
              type="button"
              disabled={!canRetry || isLoading}
            >
              Try Again
            </button>
          </div>
        )}

        {!isLoading && !hasError && activeTab === 'overview' && (
          <>
            <section className="analysis-overview-grid">
              <div className="analysis-overview-main">
                {chartData.length > 0 && (
                  <div className="analysis-chart-card">
                    <div className="analysis-chart-card__header">
                      <h3>Emotion Intensity Over Time</h3>
                      <p>Track the dominant emotions throughout the call.</p>
                      <ul className="analysis-chart-card__legend">
                        <li>🧑 = Customer</li>
                        <li>🤖 = Agent</li>
                        <li>❔ = Unknown</li>
                      </ul>
                    </div>
          <div className="chart-wrapper">
                      <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              margin={{ top: 80, right: 80, left: 80, bottom: 60 }}
            >
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                type="number"
                dataKey="time"
                domain={[
                  (dataMin) => {
                    if (typeof intervalDuration === 'number' && intervalDuration > 0) {
                      const minWithPadding = dataMin - intervalDuration / 2;
                      return minWithPadding < 0 ? 0 : minWithPadding;
                    }
                    return Math.max(0, dataMin - 5);
                  },
                  (dataMax) => {
                    if (typeof intervalDuration === 'number' && intervalDuration > 0) {
                      return dataMax + intervalDuration / 2;
                    }
                    return dataMax + 5;
                  },
                ]}
                ticks={chartData.map((entry) => entry.time)}
                tickFormatter={(value) => {
                  const interval = intervalLookup.get(value);
                  if (!interval) {
                    return `${Math.round(value)}s`;
                  }
                  return `${interval.intervalStart}s-${interval.intervalEnd}s`;
                }}
                label={{ value: 'Time (seconds)', position: 'insideBottom', offset: -10, style: { fontSize: '14px' } }}
                tick={{ fontSize: 12 }}
                scale="linear"
                allowDataOverflow
              />
              <YAxis
                label={{ value: 'Intensity', angle: -90, position: 'insideLeft', style: { fontSize: '14px' } }}
                tick={{ fontSize: 12 }}
                domain={[0, 1]}
              />
              <Tooltip
                cursor={{ fill: 'transparent' }}
                animationDuration={0}
                wrapperStyle={{
                  outline: 'none',
                  zIndex: 1000,
                  pointerEvents: 'none',
                }}
                contentStyle={{
                  backgroundColor: 'rgba(0, 0, 0, 0.9)',
                  border: '1px solid #ccc',
                  borderRadius: '4px',
                  padding: '10px',
                  pointerEvents: 'none',
                  margin: 0,
                }}
                position={{ y: -20 }}
                allowEscapeViewBox={{ x: false, y: true }}
                content={(props) => (
                  <CustomTooltip {...props} emotionColorMap={emotionColorMap} />
                )}
              />
              <Legend wrapperStyle={{ paddingTop: '20px' }} payload={legendPayload} />
              {currentTime >= 0 && chartData.length > 0 && duration > 0 && (
                <ReferenceLine
                  key={`timeline-${Math.floor(currentTime)}`}
                  x={currentTime}
                            stroke="#ff5a5a"
                  strokeWidth={4}
                  strokeDasharray="10 5"
                  isFront
                  alwaysShow
                  label={{
                    value: `▶ ${Math.round(currentTime)}s`,
                    position: 'top',
                              fill: '#ff5a5a',
                    fontSize: 14,
                    fontWeight: 'bold',
                    offset: 10,
                  }}
                />
              )}
              <Bar
                dataKey="score"
                isAnimationActive={false}
                minPointSize={6}
                barSize={Math.max(12, intervalDuration * 8)}
                shape={(shapeProps) => (
                  <SegmentBarShape
                    {...shapeProps}
                    averageDuration={intervalDuration}
                  />
                )}
              >
                {chartData.map((entry, index) => {
                  const categoryKey = typeof entry.category === 'string'
                    ? entry.category.toLowerCase()
                    : null;
                  const categoryColor = categoryKey ? CATEGORY_COLORS[categoryKey] : null;
                  const emotionColor = entry.topEmotion
                    ? emotionColorMap[entry.topEmotion]
                    : null;
                  const fillColor = emotionColor || categoryColor || CATEGORY_COLORS.neutral;

                  return (
                    <Cell
                      key={`${entry.intervalStart}-${index}`}
                      fill={fillColor}
                      stroke={entry.speaker ? (SPEAKER_COLORS[entry.speaker] || '#222222') : 'transparent'}
                      strokeWidth={entry.speaker ? 2 : 0}
                    />
                  );
                })}
                <LabelList
                  dataKey="speaker"
                  content={(labelProps) => <SpeakerLabel {...labelProps} />}
                />
              </Bar>
            </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}
          </div>

              {/* <aside className="analysis-overview-aside">
          {legendPayload.length > 0 && (
            <div className="emotion-legend-container">
                    <h3 className="emotion-legend-title">Emotion Legend</h3>
              <div className="emotion-legend-grid">
                {legendPayload.map(({ value, color }) => (
                  <div key={value} className="emotion-legend-entry">
                    <span
                      className="emotion-color-box"
                      style={{ backgroundColor: color }}
                    />
                    <span className="emotion-name">{value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

                {recordingUrl && (
                  <a
                    className="analysis-overview-link"
                    href={recordingUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    View raw recording
                  </a>
                )}
              </aside> */}
        </section>
          </>
        )}

        {!isLoading && !hasError && activeTab === 'transcript' && (
          <section className="analysis-transcript">
            <header className="analysis-transcript__header">
              <h2>Transcript</h2>
              <p>Speaker-aligned transcript segments captured during the call.</p>
            </header>
            {sortedTranscriptSegments.length > 0 ? (
              <ol className="analysis-transcript__list">
                {sortedTranscriptSegments.map((segment, index) => {
                  const speakerLabel = segment?.speaker || 'Unknown';
                  const color = SPEAKER_COLORS[speakerLabel] || '#94a3b8';
                  const text = (segment?.text || '').trim() || '…';
                  const startLabel = formatSecondsCompact(segment?.start);
                  const endLabel = formatSecondsCompact(segment?.end);

                  return (
                    <li key={`${speakerLabel}-${index}-${startLabel}`} className="transcript-item">
                      <div className="transcript-item__meta">
                        <span
                          className="transcript-item__speaker"
                          style={{ color }}
                        >
                          {speakerLabel}
                        </span>
                        <span className="transcript-item__time">
                          {startLabel}
                          {' — '}
                          {endLabel}
                        </span>
                      </div>
                      <p className="transcript-item__text">{text}</p>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <p className="analysis-transcript__empty">
                Transcript data is not available for this analysis.
              </p>
            )}
          </section>
        )}

        {!isLoading && !hasError && activeTab === 'metrics' && (
          <section className="analysis-metrics">
            <h2>Emotion Metrics</h2>
            <p className="analysis-metrics__subtitle">
              Breakdown of detected emotions grouped into positive, neutral, and negative categories.
            </p>

            <div className="analysis-metrics-toggle" role="group" aria-label="Select speaker focus for emotion metrics">
              {metricsOptions.map((option) => {
                const optionMetrics = speakerMetrics?.[option.id];
                const hasSegments = optionMetrics && (optionMetrics.segmentCount ?? 0) > 0;
                const isActive = activeMetricsSpeaker === option.id;
                const isDisabled = option.id !== 'combined' && !hasSegments;
                return (
                  <button
                    key={option.id}
                    type="button"
                    className={`analysis-tab analysis-metrics-toggle__button ${isActive ? 'is-active' : ''}`}
                    onClick={() => setActiveMetricsSpeaker(option.id)}
                    disabled={isDisabled}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            
            <div className="emotion-category-grid">
              {['positive', 'neutral', 'negative'].map((categoryKey) => {
                const labelMap = {
                  positive: 'Positive Emotions',
                  neutral: 'Neutral Emotions',
                  negative: 'Negative Emotions',
                };
                const items = activeSpeakerMetrics.categorizedEmotions[categoryKey] || [];
                const segmentCount = activeSpeakerMetrics.categoryCounts?.[categoryKey] ?? 0;

                return (
                  <div className={`emotion-category-card emotion-category-card--${categoryKey}`} key={categoryKey}>
                    <header className="emotion-category-card__header">
                      <div className="emotion-category-card__title">
                        <span className={`emotion-category-bullet emotion-category-bullet--${categoryKey}`} aria-hidden />
                        <h3>{labelMap[categoryKey]}</h3>
                      </div>
                      <span
                        className="emotion-category-card__count"
                        style={{ color: CATEGORY_COLORS[categoryKey] }}
                      >
                        {segmentCount} {segmentCount === 1 ? 'segment' : 'segments'}
                      </span>
                    </header>
                    {items.length > 0 ? (
                      <ul className="emotion-category-list">
                        {items.map((emotion) => (
                          <li key={emotion.name} className="emotion-category-list__item">
                            <div className="emotion-category-list__info">
                              <span className={`emotion-category-bullet emotion-category-bullet--${categoryKey}`} aria-hidden />
                              <span className="emotion-category-list__name">{emotion.name}</span>
                            </div>
                            <span className="emotion-category-list__meta">
                              {emotion.count}×
                          {emotion.percentage !== undefined ? ` · max score ${Math.round(emotion.percentage)}%` : ''}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="emotion-category-empty">No emotions detected in this category.</p>
                    )}
                  </div>
                );
              })}
            </div>
            <div className={`overall-emotion-card overall-emotion-card--${(activeSpeakerMetrics.overallEmotion?.label) || 'unknown'}`}>
              <div className="overall-emotion-card__header">
                <span className="overall-emotion-card__title">Overall Status</span>
                {/* {activeSpeakerMetrics.overallEmotion?.call_outcome && (
                  <span className="overall-emotion-card__tag">
                    {formatStatusLabel(activeSpeakerMetrics.overallEmotion.call_outcome)}
                  </span>
                )} */}
              </div>
              {activeSpeakerMetrics.overallEmotion ? (
                <>
                  <div className="overall-emotion-card__label">
                    {formatStatusLabel(activeSpeakerMetrics.overallEmotion.label || 'neutral')}
                  </div>
                  {/* {Number.isFinite(activeSpeakerMetrics.overallEmotion.confidence) && (
                    <div className="overall-emotion-card__confidence">
                      {Math.round(Math.max(0, Math.min(1, activeSpeakerMetrics.overallEmotion.confidence)) * 100)}% confidence
                    </div>
                  )} */}
                  {activeSpeakerMetrics.overallEmotion.reasoning && (
                    <p className="overall-emotion-card__reason">{activeSpeakerMetrics.overallEmotion.reasoning}</p>
                  )}
                </>
              ) : (
                <p className="overall-emotion-card__empty">
                  Overall emotion is not available for this analysis.
                </p>
              )}
            </div>
          </section>
        )}

        {/* {!isLoading && !hasError && activeTab === 'evaluations' && (
          <section className="analysis-placeholder">
            <h2>Evaluations</h2>
            <p>Evaluation results will be displayed here when available.</p>
          </section>
        )} */}

      </div>
    </main>
  );
}

export default AnalysisPage;

