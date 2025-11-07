import { useState, useMemo, useRef, useEffect } from 'react'
import './App.css'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine, Cell } from 'recharts'
import { analyzeAudioFile } from './services/api'
import { transformApiDataToChart } from './utils/dataTransform'


// Generate unique, visually distinct colors for emotions
// Uses HSL color space to ensure maximum color separation
function generateUniqueColors(count) {
  const colors = [];
  const hueStep = 360 / count; // Distribute hues evenly around the color wheel
  
  for (let i = 0; i < count; i++) {
    const hue = (i * hueStep) % 360;
    // Vary saturation (70-100%) and lightness (45-65%) for better distinction
    const saturation = 70 + (i % 3) * 10; // 70, 80, or 90%
    const lightness = 50 + (i % 2) * 10; // 50 or 60%
    
    // Convert HSL to RGB
    const h = hue / 360;
    const s = saturation / 100;
    const l = lightness / 100;
    
    const c = (1 - Math.abs(2 * l - 1)) * s;
    const x = c * (1 - Math.abs((h * 6) % 2 - 1));
    const m = l - c / 2;
    
    let r, g, b;
    if (h < 1/6) {
      r = c; g = x; b = 0;
    } else if (h < 2/6) {
      r = x; g = c; b = 0;
    } else if (h < 3/6) {
      r = 0; g = c; b = x;
    } else if (h < 4/6) {
      r = 0; g = x; b = c;
    } else if (h < 5/6) {
      r = x; g = 0; b = c;
    } else {
      r = c; g = 0; b = x;
    }
    
    r = Math.round((r + m) * 255);
    g = Math.round((g + m) * 255);
    b = Math.round((b + m) * 255);
    
    colors.push(`#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`);
  }
  
  return colors;
}

const CustomTooltip = ({ active, payload, emotionColorMap }) => {
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
      <p style={{ margin: 0, color: '#ffffff', fontWeight: 600 }}>{`${intervalStart}s - ${intervalEnd}s`}</p>
      {hasTopEmotion ? (
        <p
          style={{
            margin: 0,
            marginTop: 4,
            color,
            fontWeight: 500
          }}
        >
          {`${topEmotion} : ${score.toFixed(4)}`}
        </p>
      ) : (
        <p style={{ margin: 0, marginTop: 4, color: '#ffffff' }}>No detected emotion</p>
      )}
    </div>
  );
};

function App() {
  const [audioFile, setAudioFile] = useState(null)
  const [audioUrl, setAudioUrl] = useState(null)
  const [chartData, setChartData] = useState([])
  const [emotions, setEmotions] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [summary, setSummary] = useState(null)
  const [showChart, setShowChart] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [duration, setDuration] = useState(0)
  
  const audioRef = useRef(null)

  // Create color mapping for emotions - generate unique colors for each emotion
  const emotionColorMap = useMemo(() => {
    const colorMap = {};
    if (emotions.length === 0) return colorMap;
    
    // Generate exactly as many unique colors as we have emotions
    const uniqueColors = generateUniqueColors(emotions.length);
    
    emotions.forEach((emotion, index) => {
      colorMap[emotion] = uniqueColors[index];
    });
    return colorMap;
  }, [emotions]);

  const intervalDuration = useMemo(() => {
    if (chartData.length > 0) {
      return chartData[0].intervalEnd - chartData[0].intervalStart;
    }
    return 10;
  }, [chartData]);

  const legendPayload = useMemo(() => (
    emotions.map((emotion) => ({
      value: emotion,
      type: 'square',
      color: emotionColorMap[emotion] || '#888888'
    }))
  ), [emotions, emotionColorMap]);

  const intervalLookup = useMemo(() => {
    const map = new Map();
    chartData.forEach((entry) => {
      map.set(entry.time, entry);
    });
    return map;
  }, [chartData]);

  // Update current time during playback
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !audioUrl) return;

    // Only load if audio hasn't been loaded yet
    if (audio.readyState === 0) {
      audio.load();
    }

    const handleLoadedMetadata = () => {
      if (audio && !isNaN(audio.duration) && audio.duration > 0 && isFinite(audio.duration)) {
        setDuration(audio.duration);
      }
    };

    const handleLoadedData = () => {
      if (audio && !isNaN(audio.duration) && audio.duration > 0 && isFinite(audio.duration)) {
        setDuration(audio.duration);
      }
    };

    const handleCanPlay = () => {
      if (audio && !isNaN(audio.duration) && audio.duration > 0 && isFinite(audio.duration)) {
        setDuration(audio.duration);
      }
    };

    const handlePlay = () => {
      setIsPlaying(true);
    };

    const handlePause = () => {
      setIsPlaying(false);
    };

    const handleEnded = () => {
      setIsPlaying(false);
      setCurrentTime(0);
      if (audio) {
        audio.currentTime = 0;
      }
    };

    // Add event listeners
    audio.addEventListener('loadedmetadata', handleLoadedMetadata);
    audio.addEventListener('loadeddata', handleLoadedData);
    audio.addEventListener('canplay', handleCanPlay);
    audio.addEventListener('play', handlePlay);
    audio.addEventListener('playing', handlePlay);
    audio.addEventListener('pause', handlePause);
    audio.addEventListener('ended', handleEnded);

    // Listen to timeupdate event for chart synchronization
    const handleTimeUpdate = (e) => {
      const audioElement = e.target || audioRef.current;
      if (audioElement && !isNaN(audioElement.currentTime) && audioElement.currentTime >= 0 && isFinite(audioElement.currentTime)) {
        setCurrentTime(audioElement.currentTime);
      }
    };
    audio.addEventListener('timeupdate', handleTimeUpdate);
    
    // Use interval for more frequent updates (every 100ms) for smoother chart line movement
    const intervalId = setInterval(() => {
      const audioElement = audioRef.current;
      if (audioElement && !isNaN(audioElement.currentTime)) {
        setCurrentTime(audioElement.currentTime);
      }
    }, 100);

    // Initial check for duration
    if (!isNaN(audio.duration) && audio.duration > 0 && isFinite(audio.duration)) {
      setDuration(audio.duration);
    }

    return () => {
      // Clear interval
      clearInterval(intervalId);
      // Remove event listeners
      if (audio) {
        audio.removeEventListener('loadedmetadata', handleLoadedMetadata);
        audio.removeEventListener('loadeddata', handleLoadedData);
        audio.removeEventListener('canplay', handleCanPlay);
        audio.removeEventListener('play', handlePlay);
        audio.removeEventListener('playing', handlePlay);
        audio.removeEventListener('pause', handlePause);
        audio.removeEventListener('ended', handleEnded);
        audio.removeEventListener('timeupdate', handleTimeUpdate);
      }
    };
  }, [audioUrl]);

  // Cleanup audio URL when component unmounts or file changes
  useEffect(() => {
    return () => {
      if (audioUrl) {
        URL.revokeObjectURL(audioUrl);
      }
    };
  }, [audioUrl]);

  const handleFileChange = (e) => {
    const file = e.target.files[0]
    if (file && file.type.startsWith('audio/')) {
      // Clean up previous audio URL
      if (audioUrl) {
        URL.revokeObjectURL(audioUrl)
      }
      
      setAudioFile(file)
      const url = URL.createObjectURL(file)
      setAudioUrl(url)
      setShowChart(false)
      setChartData([])
      setEmotions([])
      setError(null)
      setSummary(null)
      setCurrentTime(0)
      setIsPlaying(false)
    } else {
      alert('Please upload a valid audio file')
    }
  }

  const handleAnalyze = async () => {
    if (!audioFile) {
      return
    }

    setIsLoading(true)
    setError(null)
    setShowChart(false)
    setChartData([])
    setEmotions([])
    setSummary(null)

    try {
      const response = await analyzeAudioFile(audioFile)
      
      if (response.success && response.results) {
        // Transform API data to chart format
        const { chartData: transformedData, emotions: detectedEmotions } = transformApiDataToChart(response)
        
        if (transformedData.length === 0) {
          throw new Error('No emotion data found in the analysis results')
        }

        if (detectedEmotions.length === 0) {
          throw new Error('No emotions detected in the audio file')
        }

        setChartData(transformedData)
        setEmotions(detectedEmotions)
        setSummary(response.results.summary || null)
        setShowChart(true)
        
        // Ensure audio is loaded when chart is displayed
        if (audioRef.current && audioUrl) {
          setTimeout(() => {
            if (audioRef.current) {
              audioRef.current.load()
            }
          }, 100)
        }
      } else {
        throw new Error('Invalid response from server')
      }
    } catch (err) {
      setError(err.message || 'Failed to analyze audio file. Please try again.')
      setShowChart(false)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="app-container">
      <div className="upload-section">
        <div className="upload-area">
          <input
            type="file"
            accept="audio/*"
            onChange={handleFileChange}
            id="audio-upload"
            disabled={isLoading}
            style={{ display: 'none' }}
          />
          <label 
            htmlFor="audio-upload" 
            className={`upload-label ${isLoading ? 'disabled' : ''}`}
            style={{ cursor: isLoading ? 'not-allowed' : 'pointer', opacity: isLoading ? 0.6 : 1 }}
          >
            {audioFile ? (
              <div className="file-info">
                <span className="file-icon">🎵</span>
                <span className="file-name">{audioFile.name}</span>
              </div>
            ) : (
              <div className="upload-placeholder">
                <span className="upload-icon">📁</span>
                <span>Click to upload audio file</span>
              </div>
            )}
          </label>
        </div>
        
        {audioFile && !showChart && !isLoading && (
          <button className="analyze-button" onClick={handleAnalyze}>
            Analyze
          </button>
        )}

        {isLoading && (
          <div className="loading-container">
            <div className="spinner"></div>
            <p>Analyzing audio file... This may take a moment.</p>
          </div>
        )}

        {error && (
          <div className="error-container">
            <p className="error-message">{error}</p>
            <button className="retry-button" onClick={handleAnalyze}>
              Try Again
            </button>
          </div>
        )}
      </div>

      {showChart && chartData.length > 0 && (
        <div className="chart-section">
          <h2>Emotion Analysis Results</h2>
          {summary && (
            <div className="summary-container">
              <h3>Summary</h3>
              <p>{summary}</p>
            </div>
          )}
          
          {audioUrl && (
            <div className="audio-player-container">
              <audio 
                ref={audioRef} 
                src={audioUrl} 
                controls
                preload="metadata"
                style={{ width: '100%' }}
                onLoadedMetadata={(e) => {
                  if (e.target.duration && !isNaN(e.target.duration)) {
                    setDuration(e.target.duration);
                  }
                }}
                onTimeUpdate={(e) => {
                  const audioElement = e.target;
                  if (audioElement && !isNaN(audioElement.currentTime)) {
                    setCurrentTime(audioElement.currentTime);
                  }
                }}
                onPlay={() => setIsPlaying(true)}
                onPause={() => setIsPlaying(false)}
                onEnded={() => {
                  setIsPlaying(false);
                  setCurrentTime(0);
                }}
              />
            </div>
          )}

          <div className="chart-wrapper">
            <BarChart 
              width={1400}
              height={600}
              data={chartData} 
              margin={{ top: 100, right: 120, left: 120, bottom: 60 }}
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
                  }
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
                allowDataOverflow={true}
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
                  pointerEvents: 'none'
                }}
                contentStyle={{
                  backgroundColor: 'rgba(0, 0, 0, 0.9)',
                  border: '1px solid #ccc',
                  borderRadius: '4px',
                  padding: '10px',
                  pointerEvents: 'none',
                  margin: 0
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
                  stroke="#ff0000" 
                  strokeWidth={4}
                  strokeDasharray="10 5"
                  isFront={true}
                  alwaysShow={true}
                  label={{ 
                    value: `▶ ${Math.round(currentTime)}s`, 
                    position: 'top', 
                    fill: '#ff0000',
                    fontSize: 14,
                    fontWeight: 'bold',
                    offset: 10
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
          </div>

          {legendPayload.length > 0 && (
            <div className="emotion-legend-container">
              <h3 className="emotion-legend-title">Emotion Color Reference</h3>
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
          
         
      
        </div>
      )}
    </div>
  )
}

export default App
