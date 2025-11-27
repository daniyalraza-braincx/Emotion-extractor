import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { fetchRetellCalls, getOrganizationAgents } from '../services/api';
import { useAnalysis } from '../context/AnalysisContext';
import { useAuth } from '../context/AuthContext';
import { formatTimestamp, formatDuration, formatStatusLabel } from '../utils/formatters';
import Card from '../components/Card';
import Button from '../components/Button';
import StatusBadge from '../components/StatusBadge';

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

  // Get agent_id from URL query params
  const currentAgentId = useMemo(() => {
    return searchParams.get('agent_id') || null;
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
  const [savedAgents, setSavedAgents] = useState([]);
  const [isLoadingAgents, setIsLoadingAgents] = useState(false);
  const callsPerPage = 15;

  const loadRetellCalls = useCallback(async (pageToLoad = null, agentId = null) => {
    const page = pageToLoad !== null ? pageToLoad : currentPage;
    const agentIdToUse = agentId !== null ? agentId : currentAgentId;
    if (!authenticated || loading) {
      return;
    }
    setIsFetchingCalls(true);
    setCallsError(null);
    try {
      const response = await fetchRetellCalls(page, callsPerPage, agentIdToUse);
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
  }, [authenticated, loading, currentPage, callsPerPage, currentAgentId]);

  // Load saved agents for the organization
  const loadSavedAgents = useCallback(async (orgId) => {
    if (!orgId) {
      setSavedAgents([]);
      return;
    }
    setIsLoadingAgents(true);
    try {
      const response = await getOrganizationAgents(orgId);
      if (response.success && Array.isArray(response.agents)) {
        setSavedAgents(response.agents);
      } else {
        setSavedAgents([]);
      }
    } catch (err) {
      // Silently fail - agents list is optional
      console.warn('Failed to load agents:', err);
      setSavedAgents([]);
    } finally {
      setIsLoadingAgents(false);
    }
  }, []);

  // Track previous organization ID to detect changes
  const prevOrgIdRef = useRef(currentOrganization?.id);
  const agentsLoadedRef = useRef({}); // Track which orgs have had agents loaded
  const loadingAgentsRef = useRef({}); // Track which orgs are currently loading agents
  
  // Load agents when organization changes (separate effect to avoid loops)
  useEffect(() => {
    if (!authenticated || loading) return;
    
    const currentOrgId = currentOrganization?.id;
    if (!currentOrgId) return;
    
    const prevOrgId = prevOrgIdRef.current;
    
    // If organization changed, reset tracking
    if (currentOrgId !== prevOrgId) {
      prevOrgIdRef.current = currentOrgId;
      agentsLoadedRef.current = {};
      loadingAgentsRef.current = {};
      // Clear agent_id from URL when organization changes
      const newSearchParams = new URLSearchParams(searchParams);
      newSearchParams.delete('agent_id');
      newSearchParams.set('page', '1');
      setSearchParams(newSearchParams, { replace: true });
    }
    
    // Load agents if not already loaded or loading
    if (!agentsLoadedRef.current[currentOrgId] && !loadingAgentsRef.current[currentOrgId]) {
      loadingAgentsRef.current[currentOrgId] = true;
      loadSavedAgents(currentOrgId).then(() => {
        agentsLoadedRef.current[currentOrgId] = true;
        loadingAgentsRef.current[currentOrgId] = false;
      }).catch(() => {
        loadingAgentsRef.current[currentOrgId] = false;
      });
    }
  }, [authenticated, loading, currentOrganization?.id, isAdmin, searchParams, setSearchParams, loadSavedAgents]);
  
  // Load calls when page/agent/organization changes
  useEffect(() => {
    if (!authenticated || loading) return;
    
    const currentOrgId = currentOrganization?.id;
    
    // For admins, always load calls
    if (isAdmin) {
      loadRetellCalls(currentPage);
      return;
    }
    
    // For users, load calls when organization is available
    // We can load calls even if agents haven't loaded yet (will show all calls)
    if (currentOrgId) {
      loadRetellCalls(currentPage);
    }
  }, [authenticated, loading, currentPage, currentAgentId, currentOrganization?.id, isAdmin, loadRetellCalls]);

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

  const handleAgentSelect = useCallback((agentId) => {
    const newSearchParams = new URLSearchParams(searchParams);
    if (agentId) {
      newSearchParams.set('agent_id', agentId);
    } else {
      newSearchParams.delete('agent_id');
    }
    newSearchParams.set('page', '1');
    setSearchParams(newSearchParams);
  }, [searchParams, setSearchParams]);

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
    <div className="dashboard-page">
      {hasNoOrganizations && (
        <Card className="mb-3" style={{ 
          background: '#fff8e1', 
          borderColor: '#ffc107', 
          color: '#856404'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
            <div>
              <strong>No organization found</strong>
              <p style={{ margin: '0.5rem 0 0', fontSize: '0.9rem' }}>
                You need to create an organization to start using the application.
              </p>
            </div>
            <Link to="/organizations" style={{ textDecoration: 'none' }}>
              <Button variant="primary">Create Organization</Button>
            </Link>
          </div>
        </Card>
      )}
      
      <div className="page-header">
        <div>
          <h1 className="page-header-title">Voice Agents</h1>
          <p className="page-header-subtitle">
            {totalCallCount} total calls
            {currentOrganization && ` • ${currentOrganization.name}`}
          </p>
        </div>
      </div>

      {/* Filters Bar */}
      <Card className="mb-3">
        <div style={{ display: 'flex', gap: 'var(--spacing-md)', alignItems: 'center', flexWrap: 'wrap', justifyContent: 'space-between' }}>
          {currentOrganization && (
            <div style={{ display: 'flex', gap: 'var(--spacing-sm)', alignItems: 'center', minWidth: '200px' }}>
              <label style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                Agent:
              </label>
              <select
                value={currentAgentId || ''}
                onChange={(e) => handleAgentSelect(e.target.value || null)}
                className="org-switcher-select"
                disabled={isLoadingAgents}
                style={{ flex: 1 }}
              >
                <option value="">All Agents</option>
                {savedAgents.map((agent) => (
                  <option key={agent.id} value={agent.agent_id}>
                    {agent.agent_name || agent.agent_id} ({agent.call_count} {agent.call_count === 1 ? 'call' : 'calls'})
                  </option>
                ))}
              </select>
            </div>
          )}
          
          <div style={{ flex: 1, maxWidth: '400px' }}>
            <input
              type="search"
              placeholder="Search calls..."
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              style={{
                width: '100%',
                padding: 'var(--spacing-sm) var(--spacing-md)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--border-radius)',
                fontSize: 'var(--font-size-sm)',
              }}
            />
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-sm)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={hideBlocked}
              onChange={(e) => setHideBlocked(e.target.checked)}
              style={{ cursor: 'pointer' }}
            />
            <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)' }}>
              Hide blocked
            </span>
          </label>

          <div style={{ display: 'flex', gap: 'var(--spacing-sm)', alignItems: 'center', marginLeft: 'auto' }}>
            <Button
              variant="secondary"
              onClick={() => loadRetellCalls(currentPage)}
              disabled={isFetchingCalls}
              size="small"
            >
              {isFetchingCalls ? 'Refreshing…' : 'Refresh'}
            </Button>
            <Button 
              variant="primary" 
              icon="🤖"
              onClick={triggerUpload}
              size="small"
            >
              Upload Audio
            </Button>
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
      </Card>

      {callsError && (
        <Card className="mb-3" style={{ background: '#fff6f6', borderColor: '#ffced3', color: '#ca3949' }}>
          {callsError}
        </Card>
      )}

      <div>
        {isFetchingCalls ? (
          <Card className="text-center" style={{ padding: 'var(--spacing-2xl)' }}>
            <p style={{ color: 'var(--text-secondary)' }}>Loading calls…</p>
          </Card>
        ) : totalCallCount === 0 ? (
          <Card className="text-center" style={{ padding: 'var(--spacing-2xl)' }}>
            <p style={{ color: 'var(--text-secondary)' }}>
              {!isAdmin && currentAgentId ? (
                <>No calls found for agent <strong>{currentAgentId}</strong>.</>
              ) : (
                <>Waiting for Retell to send <code>call_analyzed</code> webhooks.</>
              )}
            </p>
          </Card>
        ) : resultCount === 0 ? (
          <Card className="text-center" style={{ padding: 'var(--spacing-2xl)' }}>
            <p style={{ color: 'var(--text-secondary)' }}>
              No calls match "{searchQuery}". Try adjusting your filters.
            </p>
          </Card>
        ) : (
          <div className="grid grid-cols-1" style={{ gap: 'var(--spacing-md)' }}>
            {filteredCalls.map((call) => {
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

              return (
                <Card key={call.call_id} className="call-card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--spacing-md)' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-sm)', marginBottom: 'var(--spacing-xs)' }}>
                        <h3 style={{ margin: 0, fontSize: 'var(--font-size-lg)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--text-primary)' }}>
                          {callPurpose}
                        </h3>
                        <StatusBadge status={statusKey} label={statusLabel} />
                      </div>
                      <p style={{ margin: 0, fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)' }}>
                        {call.agent_name || call.agent_id || 'Unknown agent'} • {formatTimestamp(call.start_timestamp)}
                      </p>
                      <p style={{ margin: 'var(--spacing-xs) 0 0', fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)' }}>
                        Call ID: <code style={{ background: 'var(--bg-tertiary)', padding: '0.125rem 0.25rem', borderRadius: '4px', fontSize: '0.875em' }}>{call.call_id || '—'}</code>
                      </p>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 'var(--spacing-xs)' }}>
                      {durationLabel && (
                        <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)' }}>
                          {durationLabel}
                        </span>
                      )}
                      {shouldShowEmotion && (
                        <StatusBadge status={emotionKey} label={formattedEmotionLabel} />
                      )}
                    </div>
                  </div>
                  
                  <p style={{ margin: '0 0 var(--spacing-md)', fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                    {summaryText}
                  </p>
                  
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--spacing-sm)' }}>
                    {isBlocked ? (
                      <Button variant="secondary" disabled title={blockReason || 'Analysis unavailable'}>
                        Analysis Blocked
                      </Button>
                    ) : statusKey === 'completed' ? (
                      <Button 
                        variant="secondary" 
                        disabled
                        title="Go to 'Session Analysis' tab to view detailed analysis of this call"
                      >
                        Analyzed - View in Session Analysis Tab
                      </Button>
                    ) : (
                      <Button 
                        variant="primary" 
                        onClick={() => {
                          setAnalysisRequest({
                            type: 'retell',
                            call,
                          });
                          navigate('/analysis');
                        }}
                        title="View analysis for this call"
                      >
                        View Analysis
                      </Button>
                    )}
                  </div>
                </Card>
              );
            })}
          </div>
        )}

        {pagination.total > 0 && pagination.total_pages > 1 && (
          <Card className="mt-3" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--spacing-md)' }}>
            <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)' }}>
              Showing {showingFrom}–{showingTo} of {resultCount} calls
            </div>
            <div style={{ display: 'flex', gap: 'var(--spacing-sm)', alignItems: 'center' }}>
              <Button
                variant="secondary"
                size="small"
                onClick={() => handlePageChange(pagination.page - 1)}
                disabled={!pagination.has_prev}
              >
                Previous
              </Button>
              
              <div style={{ display: 'flex', gap: 'var(--spacing-xs)' }}>
                {Array.from({ length: pagination.total_pages }, (_, i) => i + 1).map((pageNum) => {
                  const showPage = pageNum === 1 || 
                                   pageNum === pagination.total_pages || 
                                   (pageNum >= currentPage - 1 && pageNum <= currentPage + 1);
                  
                  if (!showPage && pageNum === pagination.page - 2 && pageNum > 2) {
                    return <span key={`ellipsis-start-${pageNum}`} style={{ padding: 'var(--spacing-sm)' }}>…</span>;
                  }
                  if (!showPage && pageNum === pagination.page + 2 && pageNum < pagination.total_pages - 1) {
                    return <span key={`ellipsis-end-${pageNum}`} style={{ padding: 'var(--spacing-sm)' }}>…</span>;
                  }
                  
                  if (!showPage) {
                    return null;
                  }
                  
                  return (
                    <Button
                      key={pageNum}
                      variant={pagination.page === pageNum ? 'primary' : 'secondary'}
                      size="small"
                      onClick={() => handlePageChange(pageNum)}
                    >
                      {pageNum}
                    </Button>
                  );
                })}
              </div>
              
              <Button
                variant="secondary"
                size="small"
                onClick={() => handlePageChange(pagination.page + 1)}
                disabled={!pagination.has_next}
              >
                Next
              </Button>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

export default Dashboard;

