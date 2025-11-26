import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { getUserOrganizations, updateOrganization, deleteOrganization, getOrganizationAgents, addOrganizationAgent, deleteOrganizationAgent } from '../services/api';
import { API_BASE_URL } from '../config';
import Card from '../components/Card';
import Button from '../components/Button';

function OrganizationSettings() {
  const { user, isAdmin } = useAuth();
  const [organizations, setOrganizations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [editingOrg, setEditingOrg] = useState(null);
  const [orgName, setOrgName] = useState('');
  const [agents, setAgents] = useState({}); // { orgId: [agents] }
  const [loadingAgents, setLoadingAgents] = useState({});
  const [showAddAgent, setShowAddAgent] = useState({}); // { orgId: true/false }
  const [newAgentId, setNewAgentId] = useState('');
  const [newAgentName, setNewAgentName] = useState('');
  const [addingAgent, setAddingAgent] = useState(false);
  const agentsLoadedRef = useRef(new Set()); // Track which organizations have had agents loaded
  const [configuredOrg, setConfiguredOrg] = useState(null); // Track which organization is currently being configured

  useEffect(() => {
    loadOrganizations();
  }, []);

  const loadAgents = useCallback(async (orgId) => {
    if (agentsLoadedRef.current.has(orgId)) {
      return; // Already loaded or loading
    }
    agentsLoadedRef.current.add(orgId);
    setLoadingAgents(prev => ({ ...prev, [orgId]: true }));
    try {
      const response = await getOrganizationAgents(orgId);
      if (response.success) {
        setAgents(prev => ({ ...prev, [orgId]: response.agents || [] }));
      }
    } catch (err) {
      console.error('Failed to load agents:', err);
      setAgents(prev => ({ ...prev, [orgId]: [] }));
      agentsLoadedRef.current.delete(orgId); // Remove on error so it can retry
    } finally {
      setLoadingAgents(prev => ({ ...prev, [orgId]: false }));
    }
  }, []);

  useEffect(() => {
    // Load agents for each organization when organizations are loaded
    if (organizations.length > 0) {
      organizations.forEach((org) => {
        if (!agentsLoadedRef.current.has(org.id)) {
          loadAgents(org.id);
        }
      });
    }
  }, [organizations, loadAgents]);

  const handleAddAgent = async (orgId) => {
    if (!newAgentId.trim()) {
      setError('Agent ID is required');
      return;
    }
    setAddingAgent(true);
    setError(null);
    try {
      await addOrganizationAgent(orgId, newAgentId.trim(), newAgentName.trim() || null);
      setNewAgentId('');
      setNewAgentName('');
      setShowAddAgent(prev => ({ ...prev, [orgId]: false }));
      agentsLoadedRef.current.delete(orgId); // Allow reload
      await loadAgents(orgId);
    } catch (err) {
      setError(err.message || 'Failed to add agent');
    } finally {
      setAddingAgent(false);
    }
  };

  const handleDeleteAgent = async (orgId, agentRecordId) => {
    if (!window.confirm('Are you sure you want to remove this agent? This will not delete any calls.')) {
      return;
    }
    setError(null);
    try {
      await deleteOrganizationAgent(orgId, agentRecordId);
      agentsLoadedRef.current.delete(orgId); // Allow reload
      await loadAgents(orgId);
    } catch (err) {
      setError(err.message || 'Failed to delete agent');
    }
  };

  const loadOrganizations = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getUserOrganizations();
      if (response.success) {
        setOrganizations(response.organizations || []);
      }
    } catch (err) {
      setError(err.message || 'Failed to load organizations');
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateOrg = async (orgId) => {
    if (!orgName.trim()) return;
    setError(null);
    try {
      const response = await updateOrganization(orgId, { name: orgName.trim() });
      if (response.success) {
        setEditingOrg(null);
        setOrgName('');
        loadOrganizations();
      }
    } catch (err) {
      setError(err.message || 'Failed to update organization');
    }
  };

  const handleDeleteOrg = async (orgId, orgName) => {
    if (!window.confirm(`Are you sure you want to delete "${orgName}"? This will delete all associated calls and cannot be undone.`)) {
      return;
    }
    setError(null);
    try {
      const response = await deleteOrganization(orgId);
      if (response.success) {
        loadOrganizations();
      }
    } catch (err) {
      setError(err.message || 'Failed to delete organization');
    }
  };

  const startEdit = (org) => {
    setEditingOrg(org);
    setOrgName(org.name);
  };

  if (isAdmin) {
    return (
      <div>
        <div className="page-header">
          <div>
            <h1 className="page-header-title">Organization Settings</h1>
            <p className="page-header-subtitle">Admins do not manage organizations. Use the Admin Portal to view all organizations.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-header-title">Organization Settings</h1>
          <p className="page-header-subtitle">Manage your organizations and agents</p>
        </div>
      </div>

      {error && (
        <Card className="mb-3" style={{ background: '#fff6f6', borderColor: '#ffced3', color: '#ca3949' }}>
          {error}
        </Card>
      )}

      {loading ? (
        <Card className="text-center" style={{ padding: 'var(--spacing-2xl)' }}>
          <p style={{ color: 'var(--text-secondary)' }}>Loading...</p>
        </Card>
      ) : organizations.length === 0 ? (
        <Card className="text-center" style={{ padding: 'var(--spacing-2xl)' }}>
          <p style={{ color: 'var(--text-secondary)' }}>You don't have any organizations yet.</p>
        </Card>
      ) : (
        <div>
          <div className="grid grid-cols-1" style={{ gap: 'var(--spacing-md)' }}>
            {organizations.map((org) => (
              <Card key={org.id} className="org-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--spacing-md)' }}>
                  <div style={{ flex: 1 }}>
                    <h3 style={{ margin: '0 0 var(--spacing-xs)', fontSize: 'var(--font-size-lg)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--text-primary)' }}>
                      {org.name}
                    </h3>
                    <p style={{ margin: 0, fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)' }}>
                      Organization ID: {org.id}
                    </p>
                  </div>
                  <Button
                    variant={configuredOrg?.id === org.id ? 'secondary' : 'primary'}
                    size="small"
                    onClick={() => {
                      if (configuredOrg?.id === org.id) {
                        setConfiguredOrg(null);
                      } else {
                        setConfiguredOrg(org);
                        if (!agents[org.id]) {
                          loadAgents(org.id);
                        }
                      }
                    }}
                  >
                    {configuredOrg?.id === org.id ? 'Close' : 'Configure'}
                  </Button>
                </div>

                {configuredOrg?.id === org.id && (
                  <div style={{ marginTop: 'var(--spacing-lg)', paddingTop: 'var(--spacing-lg)', borderTop: '1px solid var(--border-color)' }}>
                    <div style={{ marginBottom: 'var(--spacing-lg)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--spacing-md)' }}>
                        <h4 style={{ margin: 0, fontSize: 'var(--font-size-base)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--text-primary)' }}>
                          Organization Details
                        </h4>
                        {org.user_role === 'owner' && (
                          <div style={{ display: 'flex', gap: 'var(--spacing-sm)' }}>
                            <Button
                              variant="secondary"
                              size="small"
                              onClick={() => {
                                setEditingOrg(org);
                                setOrgName(org.name);
                              }}
                            >
                              Edit Name
                            </Button>
                            <Button
                              variant="danger"
                              size="small"
                              onClick={() => handleDeleteOrg(org.id, org.name)}
                            >
                              Delete
                            </Button>
                          </div>
                        )}
                      </div>

                      {editingOrg?.id === org.id ? (
                        <Card className="mb-3" style={{ background: 'var(--bg-tertiary)' }}>
                          <input
                            type="text"
                            value={orgName}
                            onChange={(e) => setOrgName(e.target.value)}
                            style={{
                              width: '100%',
                              padding: 'var(--spacing-sm) var(--spacing-md)',
                              border: '1px solid var(--border-color)',
                              borderRadius: 'var(--border-radius)',
                              fontSize: 'var(--font-size-base)',
                              marginBottom: 'var(--spacing-md)',
                            }}
                            placeholder="Organization name"
                          />
                          <div style={{ display: 'flex', gap: 'var(--spacing-sm)' }}>
                            <Button variant="primary" size="small" onClick={() => handleUpdateOrg(org.id)}>
                              Save
                            </Button>
                            <Button variant="secondary" size="small" onClick={() => {
                              setEditingOrg(null);
                              setOrgName('');
                            }}>
                              Cancel
                            </Button>
                          </div>
                        </Card>
                      ) : null}
                    </div>

                    <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--spacing-md)' }}>
                    <h4 style={{ margin: 0, fontSize: 'var(--font-size-lg)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--text-primary)' }}>
                      Agents
                    </h4>
                    <Button
                      variant="primary"
                      size="small"
                      icon="+"
                      onClick={() => {
                        if (!agents[org.id]) {
                          loadAgents(org.id);
                        }
                        setShowAddAgent(prev => ({ ...prev, [org.id]: !prev[org.id] }));
                        if (!showAddAgent[org.id]) {
                          setNewAgentId('');
                          setNewAgentName('');
                        }
                      }}
                    >
                      {showAddAgent[org.id] ? 'Cancel' : 'Add Agent'}
                    </Button>
                  </div>

                  {showAddAgent[org.id] && (
                    <Card className="mb-3" style={{ background: 'var(--bg-tertiary)' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-md)' }}>
                        <div>
                          <label style={{
                            display: 'block',
                            marginBottom: 'var(--spacing-xs)',
                            fontSize: 'var(--font-size-sm)',
                            fontWeight: 'var(--font-weight-semibold)',
                            color: 'var(--text-primary)'
                          }}>
                            Agent ID *
                          </label>
                          <input
                            type="text"
                            value={newAgentId}
                            onChange={(e) => setNewAgentId(e.target.value)}
                            placeholder="Enter agent ID"
                            style={{
                              width: '100%',
                              padding: 'var(--spacing-sm) var(--spacing-md)',
                              border: '1px solid var(--border-color)',
                              borderRadius: 'var(--border-radius)',
                              fontSize: 'var(--font-size-base)',
                            }}
                          />
                        </div>
                        <div>
                          <label style={{
                            display: 'block',
                            marginBottom: 'var(--spacing-xs)',
                            fontSize: 'var(--font-size-sm)',
                            fontWeight: 'var(--font-weight-semibold)',
                            color: 'var(--text-primary)'
                          }}>
                            Agent Name (optional)
                          </label>
                          <input
                            type="text"
                            value={newAgentName}
                            onChange={(e) => setNewAgentName(e.target.value)}
                            placeholder="Enter agent name"
                            style={{
                              width: '100%',
                              padding: 'var(--spacing-sm) var(--spacing-md)',
                              border: '1px solid var(--border-color)',
                              borderRadius: 'var(--border-radius)',
                              fontSize: 'var(--font-size-base)',
                            }}
                          />
                        </div>
                        <Button
                          variant="primary"
                          onClick={() => handleAddAgent(org.id)}
                          disabled={addingAgent || !newAgentId.trim()}
                        >
                          {addingAgent ? 'Adding...' : 'Add Agent'}
                        </Button>
                      </div>
                    </Card>
                  )}

                  {loadingAgents[org.id] ? (
                    <Card className="text-center" style={{ padding: 'var(--spacing-lg)' }}>
                      <p style={{ color: 'var(--text-secondary)' }}>Loading agents...</p>
                    </Card>
                  ) : (
                    <div>
                      {agents[org.id] && agents[org.id].length > 0 ? (
                        <div className="grid grid-cols-1" style={{ gap: 'var(--spacing-md)' }}>
                          {agents[org.id].map((agent) => {
                            const webhookUrl = `${API_BASE_URL}/${encodeURIComponent(agent.agent_id)}/retell/webhook`;
                            return (
                              <Card key={agent.id} className="agent-card">
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--spacing-md)' }}>
                                  <div style={{ flex: 1 }}>
                                    <div style={{ fontWeight: 'var(--font-weight-semibold)', color: 'var(--text-primary)', fontSize: 'var(--font-size-base)', marginBottom: 'var(--spacing-xs)' }}>
                                      {agent.agent_name || agent.agent_id}
                                    </div>
                                    <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-secondary)' }}>
                                      ID: {agent.agent_id} • {agent.call_count} {agent.call_count === 1 ? 'call' : 'calls'}
                                    </div>
                                  </div>
                                  <Button
                                    variant="danger"
                                    size="small"
                                    onClick={() => handleDeleteAgent(org.id, agent.id)}
                                  >
                                    Remove
                                  </Button>
                                </div>
                                <Card style={{ background: 'var(--bg-tertiary)', padding: 'var(--spacing-md)' }}>
                                  <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-secondary)', marginBottom: 'var(--spacing-xs)', fontWeight: 'var(--font-weight-semibold)' }}>
                                    Webhook URL:
                                  </div>
                                  <code 
                                    style={{ 
                                      display: 'block', 
                                      fontSize: 'var(--font-size-xs)', 
                                      color: 'var(--color-primary)', 
                                      wordBreak: 'break-all',
                                      padding: 'var(--spacing-sm)',
                                      background: 'var(--bg-primary)',
                                      borderRadius: '4px',
                                      cursor: 'pointer',
                                      transition: 'var(--transition)',
                                    }}
                                    onClick={() => {
                                      navigator.clipboard.writeText(webhookUrl);
                                      alert('Webhook URL copied to clipboard!');
                                    }}
                                    onMouseEnter={(e) => e.target.style.background = 'var(--bg-secondary)'}
                                    onMouseLeave={(e) => e.target.style.background = 'var(--bg-primary)'}
                                    title="Click to copy"
                                  >
                                    {webhookUrl}
                                  </code>
                                </Card>
                              </Card>
                            );
                          })}
                        </div>
                      ) : (
                        <Card className="text-center" style={{ padding: 'var(--spacing-xl)', border: '1px dashed var(--border-color)' }}>
                          <p style={{ color: 'var(--text-secondary)' }}>
                            No agents added yet. Add an agent to start viewing calls.
                          </p>
                        </Card>
                      )}
                    </div>
                  )}
                  </div>
                </div>
                )}
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default OrganizationSettings;

