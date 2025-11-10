import { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchRetellCalls } from '../services/api';
import { useAnalysis } from '../context/AnalysisContext';
import { formatTimestamp, formatDuration, formatStatusLabel } from '../utils/formatters';

function Dashboard() {
  const navigate = useNavigate();
  const { setAnalysisRequest } = useAnalysis();

  const fileInputRef = useRef(null);

  const [retellCalls, setRetellCalls] = useState([]);
  const [isFetchingCalls, setIsFetchingCalls] = useState(false);
  const [callsError, setCallsError] = useState(null);

  const loadRetellCalls = useCallback(async () => {
    setIsFetchingCalls(true);
    setCallsError(null);
    try {
      const calls = await fetchRetellCalls();
      setRetellCalls(Array.isArray(calls) ? calls : []);
    } catch (err) {
      setCallsError(err.message || 'Failed to load Retell calls.');
    } finally {
      setIsFetchingCalls(false);
    }
  }, []);

  useEffect(() => {
    loadRetellCalls();
  }, [loadRetellCalls]);

  const handleAnalyzeCall = (call) => {
    if (!call?.call_id) return;
    setAnalysisRequest({
      type: 'retell',
      call,
    });
    navigate('/analysis');
  };

  const handleFileChange = (event) => {
    const [file] = event.target.files || [];
    if (!file) {
      return;
    }

    setAnalysisRequest({
      type: 'upload',
      file,
    });

    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }

    navigate('/analysis');
  };

  return (
    <main className="page-container">
      <header className="page-header">
        <div>
          <h1>Emotion Insights Dashboard</h1>
          <p className="page-subtitle">
            Review recent Retell calls or analyze a custom audio file using the Hume Emotion API.
          </p>
        </div>
        <div className="page-actions">
          <button
            type="button"
            className="refresh-button"
            onClick={loadRetellCalls}
            disabled={isFetchingCalls}
          >
            {isFetchingCalls ? 'Refreshing…' : 'Refresh Calls'}
          </button>
        </div>
      </header>

      <div className="dashboard-grid">
        <section className="card call-list-card">
          <div className="card-header">
            <div>
              <h2>Retell Calls</h2>
              <p className="card-subtitle">Newest webhooks appear at the top.</p>
            </div>
          </div>

          {callsError && (
            <div className="alert alert-error">
              {callsError}
            </div>
          )}

          <div className="call-list">
            {isFetchingCalls ? (
              <div className="call-empty">Loading calls…</div>
            ) : retellCalls.length === 0 ? (
              <div className="call-empty">
                Waiting for Retell to send <code>call_analyzed</code> webhooks.
              </div>
            ) : (
              retellCalls.map((call) => {
                const durationLabel = formatDuration(call.start_timestamp, call.end_timestamp);
                const statusLabel = formatStatusLabel(call.analysis_status);

                return (
                  <article key={call.call_id} className="call-card">
                    <div className="call-card__body">
                      <div className="call-card__row">
                        <span className="call-card__id" title={call.call_id}>
                          {call.call_id}
                        </span>
                        <span className={`status-pill status-${call.analysis_status || 'pending'}`}>
                          {statusLabel}
                        </span>
                      </div>

                      <div className="call-card__meta">
                        <span>{formatTimestamp(call.start_timestamp)}</span>
                        {durationLabel && <span>Duration: {durationLabel}</span>}
                        {call.agent_id && <span>Agent: {call.agent_id}</span>}
                      </div>

                      {call.error_message && (
                        <div className="call-card__error">
                          Last error: {call.error_message}
                        </div>
                      )}

                      {call.last_updated && (
                        <div className="call-card__note">
                          Updated {formatTimestamp(call.last_updated)}
                        </div>
                      )}
                    </div>

                    <div className="call-card__actions">
                      <button
                        type="button"
                        className="primary-button"
                        onClick={() => handleAnalyzeCall(call)}
                      >
                        Analyze
                      </button>
                    </div>
                  </article>
                );
              })
            )}
          </div>
        </section>

        <section className="card upload-card">
          <div className="card-header">
            <div>
              <h2>Upload Custom Audio</h2>
              <p className="card-subtitle">
                Send any WAV, MP3, M4A, or FLAC file through the same Hume workflow.
              </p>
            </div>
          </div>

          <div className="upload-card__body">
            <input
              ref={fileInputRef}
              id="custom-audio-upload"
              type="file"
              accept="audio/*"
              onChange={handleFileChange}
              style={{ display: 'none' }}
            />
            <label className="upload-dropzone" htmlFor="custom-audio-upload">
              <span className="upload-icon" role="img" aria-hidden>📁</span>
              <span className="upload-title">Drag &amp; drop or browse</span>
              <span className="upload-hint">Supports single audio file up to 25MB.</span>
            </label>
          </div>
        </section>
      </div>
    </main>
  );
}

export default Dashboard;

