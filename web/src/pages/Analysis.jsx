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
  ResponsiveContainer,
} from 'recharts';
import { analyzeAudioFile, analyzeRetellCall } from '../services/api';
import { transformApiDataToChart } from '../utils/dataTransform';
import { formatTimestamp, formatDuration, formatStatusLabel } from '../utils/formatters';
import { useAnalysis } from '../context/AnalysisContext';
import humanAvatar from '../assets/human.png';
import agentAvatar from '../assets/agent.png';

function generateUniqueColors(count) {
  const colors = [];
  const hueStep = 360 / (count || 1);

  for (let i = 0; i < count; i += 1) {
    const hue = (i * hueStep) % 360;
    const saturation = 70 + (i % 3) * 10;
    const lightness = 50 + (i % 2) * 10;

    const h = hue / 360;
    const s = saturation / 100;
    const l = lightness / 100;

    const c = (1 - Math.abs(2 * l - 1)) * s;
    const x = c * (1 - Math.abs(((h * 6) % 2) - 1));
    const m = l - c / 2;

    let r;
    let g;
    let b;

    if (h < 1 / 6) {
      r = c; g = x; b = 0;
    } else if (h < 2 / 6) {
      r = x; g = c; b = 0;
    } else if (h < 3 / 6) {
      r = 0; g = c; b = x;
    } else if (h < 4 / 6) {
      r = 0; g = x; b = c;
    } else if (h < 5 / 6) {
      r = x; g = 0; b = c;
    } else {
      r = c; g = 0; b = x;
    }

    const red = Math.round((r + m) * 255);
    const green = Math.round((g + m) * 255);
    const blue = Math.round((b + m) * 255);

    colors.push(`#${red.toString(16).padStart(2, '0')}${green.toString(16).padStart(2, '0')}${blue.toString(16).padStart(2, '0')}`);
  }

  return colors;
}

function CustomTooltip({ active, payload, emotionColorMap }) {
  if (!active || !payload || payload.length === 0) {
    return null;
  }

  const tooltipData = payload[0]?.payload;
  if (!tooltipData) {
    return null;
  }

  const { intervalStart, intervalEnd, topEmotion, score } = tooltipData;
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
        text: segment.text || ''
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
            <div className="speaker-timeline-track">
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
                const color = speakerColors?.[name]
                  || (segment.topEmotion
                    ? (emotionColorMap?.[segment.topEmotion] || '#6b7280')
                    : '#4b5563');
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

function AnalysisPage() {
  const navigate = useNavigate();
  const { analysisRequest } = useAnalysis();

  const audioRef = useRef(null);
  const [activeRequest, setActiveRequest] = useState(null);

  const [chartData, setChartData] = useState([]);
  const [emotions, setEmotions] = useState([]);
  const [summary, setSummary] = useState(null);
  const [timeline, setTimeline] = useState(() => createEmptyTimeline());
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

  const emotionColorMap = useMemo(() => {
    const mapping = {};
    if (emotions.length === 0) return mapping;

    const palette = generateUniqueColors(emotions.length);
    emotions.forEach((emotion, index) => {
      mapping[emotion] = palette[index];
    });
    return mapping;
  }, [emotions]);

  const intervalDuration = useMemo(() => {
    if (chartData.length === 0) return 10;
    return chartData[0].intervalEnd - chartData[0].intervalStart;
  }, [chartData]);

  const intervalLookup = useMemo(() => {
    const map = new Map();
    chartData.forEach((entry) => {
      map.set(entry.time, entry);
    });
    return map;
  }, [chartData]);

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
    setTimeline(createEmptyTimeline());
    setErrorInfo({ message: null, retryAllowed: true });
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);
  }, []);

  const runAnalysis = useCallback(async (request) => {
    if (!request) return;

    resetVisualizationState();
    setIsLoading(true);

    try {
      if (request.type === 'upload') {
        if (!request.file) {
          throw new Error('Audio file is missing from the analysis request.');
        }

        const objectUrl = URL.createObjectURL(request.file);
        updateAudioSource(objectUrl, true);

        const response = await analyzeAudioFile(request.file);
        if (!response.success || !response.results) {
          throw new Error('Invalid response from server');
        }

        const {
          chartData: transformed,
          emotions: detected,
          speakerTimeline
        } = transformApiDataToChart(response);
        if (transformed.length === 0) {
          throw new Error('No emotion data found in the analysis results');
        }

        if (detected.length === 0) {
          throw new Error('No emotions detected in the audio file');
        }

        setChartData(transformed);
        setEmotions(detected);
        setSummary(response.results.summary || null);
        setTimeline(normalizeTimeline(speakerTimeline));
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

        const response = await analyzeRetellCall(callId);

        if (!response.success || !response.results) {
          throw new Error('Invalid response from server');
        }

        if (response.recording_url) {
          updateAudioSource(response.recording_url, false);
        } else if (request.call?.recording_multi_channel_url) {
          updateAudioSource(request.call.recording_multi_channel_url, false);
        } else {
          updateAudioSource(null, false);
        }

        const {
          chartData: transformed,
          emotions: detected,
          speakerTimeline
        } = transformApiDataToChart(response);
        if (transformed.length === 0) {
          throw new Error('No emotion data found in the analysis results');
        }

        if (detected.length === 0) {
          throw new Error('No emotions detected in the call audio');
        }

        setChartData(transformed);
        setEmotions(detected);
        setSummary(response.results.summary || null);
        setTimeline(normalizeTimeline(speakerTimeline));
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
  }, [resetVisualizationState, updateAudioSource]);

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
      runAnalysis(activeRequest);
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

  const speakerColors = useMemo(() => ({
    Customer: '#8b6bff',
    Agent: '#f6a45d',
  }), []);

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
      return activeRequest?.call?.call_title
        || activeRequest?.call?.title
        || activeRequest?.call?.metadata?.title
        || analysisTitle
        || 'Call Summary';
    }
    if (activeRequest?.type === 'upload') {
      return activeRequest?.file?.name || 'Custom Upload';
    }
    return analysisTitle || 'Analysis Summary';
  }, [isRetell, activeRequest, analysisTitle]);

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
    { id: 'evaluations', label: 'Evaluations' },
    { id: 'tools', label: 'Tools' },
  ]), []);

  const hasError = Boolean(errorInfo.message);
  const errorMessage = errorInfo.message;
  const canRetry = errorInfo.retryAllowed;

  const playDisabled = !audioSource.url;
  const formattedCurrentTime = formatClockTime(currentTime);
  const formattedDuration = formatClockTime(duration);
  const playbackOptions = [1, 1.25, 1.5, 2];

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
                        <Bar dataKey="score" barSize={Math.max(20, intervalDuration * 3)} maxBarSize={60}>
                          {chartData.map((entry, index) => (
                            <Cell
                              key={`${entry.intervalStart}-${index}`}
                              fill={entry.topEmotion ? (emotionColorMap[entry.topEmotion] || '#999999') : '#555555'}
                            />
                          ))}
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
          <section className="analysis-placeholder">
            <h2>Transcript</h2>
            <p>Transcript data will appear here once it is available from the analysis backend.</p>
          </section>
        )}

        {!isLoading && !hasError && activeTab === 'metrics' && (
          <section className="analysis-placeholder">
            <h2>Metrics</h2>
            <p>Additional metrics will be surfaced here in a future release.</p>
          </section>
        )}

        {!isLoading && !hasError && activeTab === 'evaluations' && (
          <section className="analysis-placeholder">
            <h2>Evaluations</h2>
            <p>Evaluation results will be displayed here when available.</p>
          </section>
        )}

        {!isLoading && !hasError && activeTab === 'tools' && (
          <section className="analysis-placeholder">
            <h2>Tools</h2>
            <p>Connect workflow tools and playbooks from this panel in the future.</p>
          </section>
        )}
      </div>
    </main>
  );
}

export default AnalysisPage;

