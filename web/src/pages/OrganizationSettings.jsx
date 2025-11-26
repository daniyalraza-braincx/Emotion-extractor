import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { getUserOrganizations, updateOrganization, deleteOrganization } from '../services/api';

function OrganizationSettings() {
  const { user, isAdmin } = useAuth();
  const [organizations, setOrganizations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [editingOrg, setEditingOrg] = useState(null);
  const [orgName, setOrgName] = useState('');

  useEffect(() => {
    loadOrganizations();
  }, []);

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
      <div style={{ padding: '2rem', textAlign: 'center' }}>
        <h1>Organization Settings</h1>
        <p>Admins do not manage organizations. Use the Admin Portal to view all organizations.</p>
      </div>
    );
  }

  return (
    <div style={{ padding: '2rem', maxWidth: '800px', margin: '0 auto' }}>
      <h1>Organization Settings</h1>

      {error && (
        <div style={{ padding: '1rem', background: '#fee', color: '#c33', marginBottom: '1rem', borderRadius: '4px' }}>
          {error}
        </div>
      )}

      {loading ? (
        <div>Loading...</div>
      ) : organizations.length === 0 ? (
        <div style={{ padding: '2rem', textAlign: 'center', background: '#f3f4f6', borderRadius: '8px' }}>
          <p>You don't have any organizations yet.</p>
        </div>
      ) : (
        <div>
          <h2>Your Organizations</h2>
          <div style={{ marginBottom: '1rem', padding: '0.75rem', background: '#f0f3ff', borderRadius: '8px', fontSize: '0.85rem', color: '#5c6478' }}>
            <strong>Webhook URL format:</strong> <code style={{ background: '#fff', padding: '0.2rem 0.4rem', borderRadius: '4px' }}>/{'{'}org_id{'}'}/retell/webhook</code>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '1rem' }}>
            <thead>
              <tr style={{ background: '#f3f4f6' }}>
                <th style={{ padding: '0.75rem', textAlign: 'left', border: '1px solid #ddd' }}>Name</th>
                <th style={{ padding: '0.75rem', textAlign: 'left', border: '1px solid #ddd' }}>ID</th>
                <th style={{ padding: '0.75rem', textAlign: 'left', border: '1px solid #ddd' }}>Role</th>
                <th style={{ padding: '0.75rem', textAlign: 'left', border: '1px solid #ddd' }}>Created</th>
                <th style={{ padding: '0.75rem', textAlign: 'left', border: '1px solid #ddd' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {organizations.map((org) => (
                <tr key={org.id}>
                  <td style={{ padding: '0.75rem', border: '1px solid #ddd' }}>
                    {editingOrg?.id === org.id ? (
                      <input
                        type="text"
                        value={orgName}
                        onChange={(e) => setOrgName(e.target.value)}
                        style={{ width: '100%', padding: '0.25rem', border: '1px solid #ddd', borderRadius: '4px' }}
                      />
                    ) : (
                      org.name
                    )}
                  </td>
                  <td style={{ padding: '0.75rem', border: '1px solid #ddd' }}>
                    <code style={{ background: '#f0f3ff', padding: '0.2rem 0.4rem', borderRadius: '4px', fontSize: '0.85rem' }}>{org.id}</code>
                  </td>
                  <td style={{ padding: '0.75rem', border: '1px solid #ddd' }}>{org.user_role || 'member'}</td>
                  <td style={{ padding: '0.75rem', border: '1px solid #ddd' }}>
                    {org.created_at ? new Date(org.created_at).toLocaleDateString() : '-'}
                  </td>
                  <td style={{ padding: '0.75rem', border: '1px solid #ddd' }}>
                    {editingOrg?.id === org.id ? (
                      <>
                        <button
                          onClick={() => handleUpdateOrg(org.id)}
                          style={{ marginRight: '0.5rem', padding: '0.25rem 0.5rem', cursor: 'pointer' }}
                        >
                          Save
                        </button>
                        <button
                          onClick={() => {
                            setEditingOrg(null);
                            setOrgName('');
                          }}
                          style={{ padding: '0.25rem 0.5rem', cursor: 'pointer' }}
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        {org.user_role === 'owner' && (
                          <>
                            <button
                              onClick={() => startEdit(org)}
                              style={{ marginRight: '0.5rem', padding: '0.25rem 0.5rem', cursor: 'pointer' }}
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => handleDeleteOrg(org.id, org.name)}
                              style={{ padding: '0.25rem 0.5rem', cursor: 'pointer', color: '#c33' }}
                            >
                              Delete
                            </button>
                          </>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default OrganizationSettings;

