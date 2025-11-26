import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { fetchRetellCalls } from '../services/api';
import { useAnalysis } from '../context/AnalysisContext';
import { useAuth } from '../context/AuthContext';
import { formatTimestamp, formatDuration, formatStatusLabel } from '../utils/formatters';
import OrganizationSwitcher from '../components/OrganizationSwitcher';

function Dashboard() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { setAnalysisRequest } = useAnalysis();
  const { logout, authenticated, loading, user, isAdmin, currentOrganization, organizations } = useAuth();

  const fileInputRef = useRef(null);

  // Get page from URL query params, default to 1
  const currentPage = useMemo(() => {
    const pageParam = searchParams.get('page');
    const page = parseInt(pageParam || '1', 10);
    return isNaN(page) || page < 1 ? 1 : page;
  }, [searchParams]);

  const [retellCalls, setRetellCalls] = useState([]);
  const [pagination, setPagination] = useState({
    page: 1,
    per_page: 15,
    total: 0,
    total_pages: 1,
    has_next: false,
    has_prev: false,
  });
  const [isFetchingCalls, setIsFetchingCalls] = useState(false);
  const [callsError, setCallsError] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [hideBlocked, setHideBlocked] = useState(false);
  const callsPerPage = 15;

  const loadRetellCalls = useCallback(async (pageToLoad) => {
    const page = pageToLoad || currentPage;
    if (!authenticated || loading) {
      return;
    }
    setIsFetchingCalls(true);
    setCallsError(null);
    try {
      const response = await fetchRetellCalls(page, callsPerPage);
      setRetellCalls(Array.isArray(response.calls) ? response.calls : []);
      setPagination(response.pagination || {
        page: page,
        per_page: callsPerPage,
        total: 0,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      });
    } catch (err) {
      setCallsError(err.message || 'Failed to load Retell calls.');
    } finally {
      setIsFetchingCalls(false);
    }
  }, [authenticated, loading, currentPage, callsPerPage, currentOrganization?.id]);

  // Track previous organization ID to detect changes
  const prevOrgIdRef = useRef(currentOrganization?.id);
  
  useEffect(() => {
    if (authenticated && !loading) {
      const currentOrgId = currentOrganization?.id;
      const prevOrgId = prevOrgIdRef.current;
      
      // If organization changed, reset to page 1
      if (currentOrgId !== undefined && currentOrgId !== prevOrgId && prevOrgId !== undefined) {
        prevOrgIdRef.current = currentOrgId;
        if (currentPage !== 1) {
          const newSearchParams = new URLSearchParams(searchParams);
          newSearchParams.set('page', '1');
          setSearchParams(newSearchParams, { replace: true });
          return; // Will reload when page changes
        }
      } else {
        prevOrgIdRef.current = currentOrgId;
      }
      
      // Load calls for current page
      loadRetellCalls(currentPage);
    }
  }, [authenticated, loading, currentPage, loadRetellCalls, currentOrganization?.id, searchParams, setSearchParams]);

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
    let filtered = retellCalls;

    // Filter out blocked calls if hideBlocked is enabled
    if (hideBlocked) {
      filtered = filtered.filter((call) => {
        const rawStatus = (call.analysis_status || call.status || (call.analysis_allowed === false ? 'blocked' : 'pending')).toString();
        const statusKey = rawStatus.replace(/\s+/g, '-').toLowerCase();
        const isBlocked = statusKey === 'blocked' || call.analysis_allowed === false;
        return !isBlocked;
      });
    }

    // Apply search query filter
    if (!searchQuery.trim()) {
      return filtered;
    }

    const query = searchQuery.trim().toLowerCase();
    return filtered.filter((call) => {
      const idMatch = call.call_id?.toLowerCase().includes(query);
      const agentMatch = call.agent_id?.toLowerCase().includes(query) || call.agent_name?.toLowerCase().includes(query);
      const statusMatch = call.analysis_status?.toLowerCase().includes(query);
      const purposeMatch = call.call_purpose?.toLowerCase().includes(query);
      const summaryMatch = call.call_summary?.toLowerCase().includes(query);
      const overallEmotionLabel = call.overall_emotion_label || call.overall_emotion?.label;
      const overallEmotionMatch = overallEmotionLabel?.toLowerCase().includes(query);
      return idMatch || agentMatch || statusMatch || purposeMatch || summaryMatch || overallEmotionMatch;
    });
  }, [retellCalls, searchQuery, hideBlocked]);

  // Reset to page 1 when filters change and update URL
  useEffect(() => {
    if (currentPage !== 1) {
      const newSearchParams = new URLSearchParams(searchParams);
      newSearchParams.set('page', '1');
      setSearchParams(newSearchParams, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery, hideBlocked]); // Only reset when filters change, not when page changes

  const handlePageChange = useCallback((newPage) => {
    if (newPage >= 1 && newPage <= pagination.total_pages) {
      const newSearchParams = new URLSearchParams(searchParams);
      newSearchParams.set('page', String(newPage));
      setSearchParams(newSearchParams);
      // Scroll to top of table
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, [pagination.total_pages, searchParams, setSearchParams]);

  const renderSummary = useCallback((call) => {
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
  }, []);

  const totalCallCount = pagination.total || 0;
  const resultCount = filteredCalls.length;
  const showingFrom = pagination.total > 0 ? (pagination.page - 1) * pagination.per_page + 1 : 0;
  const showingTo = Math.min(pagination.page * pagination.per_page, pagination.total);

  // Check if user has no organizations
  const hasNoOrganizations = !isAdmin && (!organizations || organizations.length === 0);

  return (
    <main className="calls-page">
      {hasNoOrganizations && (
        <div className="alert" style={{ 
          background: '#fff8e1', 
          borderColor: '#ffc107', 
          color: '#856404',
          marginBottom: '1.5rem'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
            <div>
              <strong>No organization found</strong>
              <p style={{ margin: '0.5rem 0 0', fontSize: '0.9rem' }}>
                You need to create an organization to start using the application. Click the button below to create one.
              </p>
            </div>
            <Link
              to="/organizations"
              className="upload-button"
              style={{ textDecoration: 'none', color: 'inherit' }}
            >
              Create Organization
            </Link>
          </div>
        </div>
      )}
      
      <header className="calls-header">
        <div className="calls-header__title">
          <h1>Calls</h1>
          <p>{totalCallCount} total calls</p>
          {currentOrganization && (
            <p style={{ fontSize: '0.875rem', color: '#666', marginTop: '0.25rem' }}>
              Organization: {currentOrganization.name} (ID: {currentOrganization.id})
            </p>
          )}
        </div>

        <div className="calls-header__tools">
          {!isAdmin && <OrganizationSwitcher />}
          <div className="calls-search">
            <span aria-hidden className="calls-search__icon">🔍</span>
            <input
              type="search"
              placeholder="Search by agent, call ID, or emotion..."
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>

          <div className="calls-filter">
            <label className="calls-filter__label">
              <input
                type="checkbox"
                checked={hideBlocked}
                onChange={(e) => setHideBlocked(e.target.checked)}
                className="calls-filter__checkbox"
              />
              <span>Hide blocked calls</span>
            </label>
          </div>

          <div className="calls-toolbar">
            {isAdmin && (
              <Link
                to="/admin"
                className="toolbar-chip"
                style={{ textDecoration: 'none', color: 'inherit' }}
              >
                Admin Portal
              </Link>
            )}
            {!isAdmin && (
              <Link
                to="/organizations"
                className="toolbar-chip"
                style={{ textDecoration: 'none', color: 'inherit' }}
              >
                Organizations
              </Link>
            )}
            <button
              type="button"
              className="toolbar-chip"
              onClick={() => loadRetellCalls(currentPage)}
              disabled={isFetchingCalls}
            >
              {isFetchingCalls ? 'Refreshing…' : 'Refresh'}
            </button>
            <button type="button" className="upload-button" onClick={triggerUpload}>
              <span aria-hidden className="upload-button__icon">＋</span>
              Upload
            </button>
            <button
              type="button"
              className="toolbar-chip"
              onClick={logout}
              title="Logout"
            >
              Logout
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
            <span className="calls-table-meta__label">Call ID</span>
            <span className="calls-table-meta__label">Purpose</span>
            <span className="calls-table-meta__label calls-table-meta__label--wide">Summary</span>
            <span className="calls-table-meta__label">Duration</span>
            <span className="calls-table-meta__label">Overall Emotion</span>
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
              const purposeCandidate = [call.call_purpose, call.callPurpose]
                .find((value) => typeof value === 'string' && value.trim());
              const callPurpose = (purposeCandidate ? purposeCandidate.trim() : '') || 'Purpose unavailable';
              const summaryText = renderSummary(call);
              const rawEmotionLabel = call.overall_emotion_label || call.overall_emotion?.label;
              const formattedEmotionLabel = rawEmotionLabel ? formatStatusLabel(rawEmotionLabel) : '—';
              const emotionKey = rawEmotionLabel ? rawEmotionLabel.toLowerCase() : null;
              const shouldShowEmotion = statusKey === 'completed' && formattedEmotionLabel !== '—';
              const emotionClassName = shouldShowEmotion && emotionKey
                ? `emotion-pill emotion-${emotionKey}`
                : 'emotion-pill emotion-pill--empty';

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

                  <div className="calls-table-cell calls-table-cell--id">
                    <span className="cell-primary">{call.call_id || '—'}</span>
                  </div>

                  <div className="calls-table-cell calls-table-cell--purpose">
                    <span className="cell-primary">{callPurpose}</span>
                    <span className="cell-secondary">{call.agent_name || call.agent_id || 'Unknown agent'}</span>
                  </div>

                  <div className="calls-table-cell calls-table-cell--summary">
                    <p>{summaryText}</p>
                  </div>

                  <div className="calls-table-cell calls-table-cell--duration">
                    {durationLabel ? (
                      <span className="cell-primary">{durationLabel}</span>
                    ) : (
                      <span className="cell-secondary">Pending</span>
                    )}
                  </div>

                  <div className="calls-table-cell calls-table-cell--emotion">
                    <span className={emotionClassName}>
                      {shouldShowEmotion ? formattedEmotionLabel : '—'}
                    </span>
                  </div>

                  <div className="calls-table-cell calls-table-cell--entry">
                    <span className={`status-pill status-${statusKey}`}>
                      {statusLabel}
                    </span>
                  </div>

                  <div className="calls-table-cell calls-table-cell--actions">
                    {isBlocked ? (
                      <button
                        type="button"
                        className="row-action row-action--disabled"
                        disabled
                        aria-disabled="true"
                        title={blockReason || 'Analysis unavailable'}
                      >
                        View analysis
                      </button>
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

        {pagination.total > 0 && pagination.total_pages > 1 && (
          <div className="calls-pagination">
            <div className="calls-pagination__info">
              Showing {showingFrom}–{showingTo} of {resultCount} calls
            </div>
            <div className="calls-pagination__controls">
              <button
                type="button"
                className="pagination-button"
                onClick={() => handlePageChange(pagination.page - 1)}
                disabled={!pagination.has_prev}
                aria-label="Previous page"
              >
                Previous
              </button>
              
              <div className="pagination-pages">
                {Array.from({ length: pagination.total_pages }, (_, i) => i + 1).map((pageNum) => {
                  // Show first page, last page, current page, and pages around current
                  const showPage = pageNum === 1 || 
                                   pageNum === pagination.total_pages || 
                                   (pageNum >= currentPage - 1 && pageNum <= currentPage + 1);
                  
                  if (!showPage && pageNum === pagination.page - 2 && pageNum > 2) {
                    return <span key={`ellipsis-start-${pageNum}`} className="pagination-ellipsis">…</span>;
                  }
                  if (!showPage && pageNum === pagination.page + 2 && pageNum < pagination.total_pages - 1) {
                    return <span key={`ellipsis-end-${pageNum}`} className="pagination-ellipsis">…</span>;
                  }
                  
                  if (!showPage) {
                    return null;
                  }
                  
                  return (
                    <button
                      key={pageNum}
                      type="button"
                      className={`pagination-button pagination-button--page ${pagination.page === pageNum ? 'pagination-button--active' : ''}`}
                      onClick={() => handlePageChange(pageNum)}
                      aria-label={`Page ${pageNum}`}
                      aria-current={pagination.page === pageNum ? 'page' : undefined}
                    >
                      {pageNum}
                    </button>
                  );
                })}
              </div>
              
              <button
                type="button"
                className="pagination-button"
                onClick={() => handlePageChange(pagination.page + 1)}
                disabled={!pagination.has_next}
                aria-label="Next page"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}

export default Dashboard;

