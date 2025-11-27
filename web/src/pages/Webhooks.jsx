import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { getAllUserAgents, updateAgent } from '../services/api';
import Card from '../components/Card';
import Button from '../components/Button';

function Webhooks() {
  const { user, organizations } = useAuth();
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [editingWebhook, setEditingWebhook] = useState(null); // agent record ID
  const [webhookUrl, setWebhookUrl] = useState('');

  const loadAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getAllUserAgents();
      if (response.success) {
        setAgents(Array.isArray(response.agents) ? response.agents : []);
      }
    } catch (err) {
      setError(err.message || 'Failed to load agents');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  const handleUpdateWebhook = async (orgId, agentId) => {
    setError(null);
    try {
      const response = await updateAgent(orgId, agentId, {
        webhook_url: webhookUrl.trim() || null,
      });
      if (response.success) {
        setEditingWebhook(null);
        setWebhookUrl('');
        await loadAgents();
      }
    } catch (err) {
      setError(err.message || 'Failed to update webhook URL');
    }
  };

  // Group agents by organization
  const agentsByOrg = agents.reduce((acc, agent) => {
    const orgId = agent.organization_id;
    if (!acc[orgId]) {
      acc[orgId] = {
        orgName: agent.organization_name,
        orgId: agent.organization_org_id,
        agents: [],
      };
    }
    acc[orgId].agents.push(agent);
    return acc;
  }, {});

  const orgIds = Object.keys(agentsByOrg).sort((a, b) => 
    agentsByOrg[a].orgName.localeCompare(agentsByOrg[b].orgName)
  );

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-header-title">Webhooks</h1>
          <p className="page-header-subtitle">
            Configure n8n webhook URLs for analyzed call results by agent
          </p>
        </div>
      </div>

      {error && (
        <Card className="mb-3" style={{ background: '#fff6f6', borderColor: '#ffced3', color: '#ca3949' }}>
          {error}
        </Card>
      )}

      {loading ? (
        <Card className="text-center" style={{ padding: 'var(--spacing-2xl)' }}>
          <p style={{ color: 'var(--text-secondary)' }}>Loading agents...</p>
        </Card>
      ) : agents.length === 0 ? (
        <Card className="text-center" style={{ padding: 'var(--spacing-2xl)' }}>
          <p style={{ color: 'var(--text-secondary)' }}>
            No agents found. Add agents to your organizations in Settings first.
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1" style={{ gap: 'var(--spacing-lg)' }}>
          {orgIds.map((orgId) => {
            const orgData = agentsByOrg[orgId];
            return (
              <Card key={orgId}>
                <h3 style={{ 
                  margin: '0 0 var(--spacing-md)', 
                  fontSize: 'var(--font-size-lg)', 
                  fontWeight: 'var(--font-weight-semibold)',
                  color: 'var(--text-primary)'
                }}>
                  {orgData.orgName}
                </h3>
                <p style={{ 
                  margin: '0 0 var(--spacing-lg)', 
                  fontSize: 'var(--font-size-sm)', 
                  color: 'var(--text-secondary)' 
                }}>
                  Organization ID: <code style={{ 
                    background: 'var(--bg-tertiary)', 
                    padding: '0.125rem 0.25rem', 
                    borderRadius: '4px', 
                    fontSize: '0.875em' 
                  }}>{orgData.orgId || orgId}</code>
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-md)' }}>
                  {orgData.agents.map((agent) => (
                    <Card key={agent.id} style={{ background: 'var(--bg-tertiary)' }}>
                      <div style={{ 
                        display: 'flex', 
                        justifyContent: 'space-between', 
                        alignItems: 'flex-start', 
                        gap: 'var(--spacing-md)',
                        flexWrap: 'wrap'
                      }}>
                        <div style={{ flex: 1, minWidth: '200px' }}>
                          <div style={{ 
                            display: 'flex', 
                            alignItems: 'center', 
                            gap: 'var(--spacing-sm)',
                            marginBottom: 'var(--spacing-xs)'
                          }}>
                            <h4 style={{ 
                              margin: 0, 
                              fontSize: 'var(--font-size-base)', 
                              fontWeight: 'var(--font-weight-semibold)',
                              color: 'var(--text-primary)'
                            }}>
                              {agent.agent_name || 'Unnamed Agent'}
                            </h4>
                          </div>
                          <p style={{ 
                            margin: 0, 
                            fontSize: 'var(--font-size-sm)', 
                            color: 'var(--text-secondary)',
                            fontFamily: 'monospace'
                          }}>
                            {agent.agent_id}
                          </p>
                        </div>
                        <div style={{ flex: 1, minWidth: '300px' }}>
                          {editingWebhook === agent.id ? (
                            <div>
                              <input
                                type="url"
                                value={webhookUrl}
                                onChange={(e) => setWebhookUrl(e.target.value)}
                                style={{
                                  width: '100%',
                                  padding: 'var(--spacing-sm) var(--spacing-md)',
                                  border: '1px solid var(--border-color)',
                                  borderRadius: 'var(--border-radius)',
                                  fontSize: 'var(--font-size-base)',
                                  marginBottom: 'var(--spacing-sm)',
                                  fontFamily: 'monospace',
                                }}
                                placeholder="https://your-n8n-instance.com/webhook/..."
                              />
                              <p style={{ 
                                fontSize: 'var(--font-size-xs)', 
                                color: 'var(--text-secondary)', 
                                margin: '0 0 var(--spacing-sm)' 
                              }}>
                                When analysis completes for calls from this agent, results will be sent to this webhook.
                              </p>
                              <div style={{ display: 'flex', gap: 'var(--spacing-sm)' }}>
                                <Button 
                                  variant="primary" 
                                  size="small" 
                                  onClick={() => handleUpdateWebhook(agent.organization_id, agent.id)}
                                >
                                  Save
                                </Button>
                                <Button 
                                  variant="secondary" 
                                  size="small" 
                                  onClick={() => {
                                    setEditingWebhook(null);
                                    setWebhookUrl('');
                                  }}
                                >
                                  Cancel
                                </Button>
                                {agent.webhook_url && (
                                  <Button 
                                    variant="danger" 
                                    size="small" 
                                    onClick={() => {
                                      setWebhookUrl('');
                                      handleUpdateWebhook(agent.organization_id, agent.id);
                                    }}
                                  >
                                    Clear
                                  </Button>
                                )}
                              </div>
                            </div>
                          ) : (
                            <div>
                              <div style={{ 
                                padding: 'var(--spacing-sm)', 
                                background: 'var(--bg-primary)', 
                                borderRadius: 'var(--border-radius)', 
                                fontSize: 'var(--font-size-sm)',
                                marginBottom: 'var(--spacing-sm)',
                                wordBreak: 'break-all'
                              }}>
                                {agent.webhook_url ? (
                                  <code style={{ color: 'var(--text-primary)' }}>{agent.webhook_url}</code>
                                ) : (
                                  <span style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                                    No webhook URL configured
                                  </span>
                                )}
                              </div>
                              <Button 
                                variant="secondary" 
                                size="small" 
                                onClick={() => {
                                  setEditingWebhook(agent.id);
                                  setWebhookUrl(agent.webhook_url || '');
                                }}
                              >
                                {agent.webhook_url ? 'Edit' : 'Set Webhook'}
                              </Button>
                            </div>
                          )}
                        </div>
                      </div>
                    </Card>
                  ))}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default Webhooks;

