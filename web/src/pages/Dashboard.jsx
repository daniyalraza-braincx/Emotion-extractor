import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
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
  const [searchQuery, setSearchQuery] = useState('');

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

  const triggerUpload = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const filteredCalls = useMemo(() => {
    if (!searchQuery.trim()) {
      return retellCalls;
    }

    const query = searchQuery.trim().toLowerCase();
    return retellCalls.filter((call) => {
      const idMatch = call.call_id?.toLowerCase().includes(query);
      const agentMatch = call.agent_id?.toLowerCase().includes(query) || call.agent_name?.toLowerCase().includes(query);
      const statusMatch = call.analysis_status?.toLowerCase().includes(query);
      return idMatch || agentMatch || statusMatch;
    });
  }, [retellCalls, searchQuery]);

  const renderSummary = (call) => {
    const rawStatus = (call.analysis_status || call.status || (call.analysis_allowed === false ? 'blocked' : 'pending')).toString();
    const statusKey = rawStatus.replace(/\s+/g, '-').toLowerCase();
    const isBlocked = statusKey === 'blocked' || call.analysis_allowed === false;
    const blockReason = (call.analysis_block_reason || '').trim();

    if (isBlocked) {
      return blockReason || 'Analysis unavailable for this call.';
    }

    if (call.error_message) {
      return `Last error: ${call.error_message}`;
    }

    const agentName = call.agent_name || call.agent_id || 'Unknown agent';
    const statusLabel = formatStatusLabel(call.analysis_status);
    const transcriptUpdate = call.last_updated ? `Updated ${formatTimestamp(call.last_updated)}` : null;

    const parts = [
      `${agentName} engaged the customer.`,
      `Analysis ${statusLabel.toLowerCase()}.`,
    ];

    return parts.join(' ');
  };

  const totalCallCount = retellCalls.length;
  const resultCount = filteredCalls.length;

  return (
    <main className="calls-page">
      <header className="calls-header">
        <div className="calls-header__title">
          <h1>Calls</h1>
          <p>{totalCallCount} total calls</p>
        </div>

        <div className="calls-header__tools">
          <div className="calls-search">
            <span aria-hidden className="calls-search__icon">🔍</span>
            <input
              type="search"
              placeholder="Search by transcript, agent, or call ID..."
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>

          <div className="calls-toolbar">
           
            <button
              type="button"
              className="toolbar-chip"
              onClick={loadRetellCalls}
              disabled={isFetchingCalls}
            >
              {isFetchingCalls ? 'Refreshing…' : 'Refresh'}
            </button>
            <button type="button" className="upload-button" onClick={triggerUpload}>
              <span aria-hidden className="upload-button__icon">＋</span>
              Upload
            </button>
            <input
              ref={fileInputRef}
              id="custom-audio-upload"
              type="file"
              accept="audio/*"
              onChange={handleFileChange}
              style={{ display: 'none' }}
            />
          </div>
        </div>
      </header>

      {callsError && (
        <div className="alert alert-error calls-alert">
          {callsError}
        </div>
      )}

      <section className="calls-table-card">
        <div className="calls-table-header">
          <div className="calls-table-meta">
            <span className="calls-table-meta__label">Call Logs</span>
            <span className="calls-table-meta__label">Title</span>
            <span className="calls-table-meta__label calls-table-meta__label--wide">Summary</span>
            <span className="calls-table-meta__label">Labels</span>
            <span className="calls-table-meta__label">Duration</span>
            <span className="calls-table-meta__label">Entry</span>
            <span className="calls-table-meta__label" aria-hidden />
          </div>
        </div>

        <div className="calls-table-body">
          {isFetchingCalls ? (
            <div className="call-empty">Loading calls…</div>
          ) : totalCallCount === 0 ? (
            <div className="call-empty">
              Waiting for Retell to send <code>call_analyzed</code> webhooks.
            </div>
          ) : resultCount === 0 ? (
            <div className="call-empty">
              No calls match “{searchQuery}”. Try adjusting your filters.
            </div>
          ) : (
            filteredCalls.map((call) => {
              const durationLabel = formatDuration(call.start_timestamp, call.end_timestamp);
              const statusLabel = formatStatusLabel(call.analysis_status);
              const rawStatus = (call.analysis_status || call.status || (call.analysis_allowed === false ? 'blocked' : 'pending')).toString();
              const statusKey = rawStatus.replace(/\s+/g, '-').toLowerCase();
              const isBlocked = statusKey === 'blocked' || call.analysis_allowed === false;
              const blockReason = (call.analysis_block_reason || call.error_message || '').trim();

              return (
                <article key={call.call_id} className="calls-table-row" data-status={statusKey}>
                  <div className="calls-table-cell calls-table-cell--start">
                    <span className="cell-primary">{formatTimestamp(call.start_timestamp)}</span>
                    {call.last_updated && (
                      <span className="cell-secondary">
                        Updated {formatTimestamp(call.last_updated)}
                      </span>
                    )}
                  </div>

                  <div className="calls-table-cell calls-table-cell--title">
                    <span className="cell-primary">Callback Request</span>
                    <span className="cell-secondary">{call.agent_name || call.agent_id || 'Unknown agent'}</span>
                  </div>

                  <div className="calls-table-cell calls-table-cell--summary">
                    <p>{renderSummary(call)}</p>
                  </div>

                  <div className="calls-table-cell calls-table-cell--labels">
                    <button type="button" className="label-button">Add label ＋</button>
                  </div>

                  <div className="calls-table-cell calls-table-cell--duration">
                    {durationLabel ? (
                      <span className="cell-primary">{durationLabel}</span>
                    ) : (
                      <span className="cell-secondary">Pending</span>
                    )}
                  </div>

                  <div className="calls-table-cell calls-table-cell--entry">
                    <span className={`status-pill status-${statusKey}`}>
                      {statusLabel}
                    </span>
                  </div>

                  <div className="calls-table-cell calls-table-cell--actions">
                    {isBlocked ? (
                      <span className="row-action row-action--disabled">Analysis unavailable</span>
                    ) : (
                      <button
                        type="button"
                        className="row-action"
                        onClick={() => handleAnalyzeCall(call)}
                      >
                        View analysis
                      </button>
                    )}
                  </div>
                </article>
              );
            })
          )}
        </div>
      </section>
    </main>
  );
}

export default Dashboard;

