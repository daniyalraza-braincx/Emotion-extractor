import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { createOrganization, getAllOrganizationsForAdmin } from '../services/api';
import { getToken } from '../services/auth';

function OrganizationSwitcher() {
  const { currentOrganization, organizations, switchOrganization, user, isAdmin, fetchUserInfo } = useAuth();
  const navigate = useNavigate();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newOrgName, setNewOrgName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSwitch = async (orgId) => {
    if (!orgId || orgId === currentOrganization?.id) return;
    setLoading(true);
    setError(null);
    try {
      const result = await switchOrganization(Number(orgId));
      if (!result.success) {
        setError(result.error || 'Failed to switch organization');
      } else {
        // Refresh organizations for admins to get updated list
        if (isAdmin && fetchUserInfo) {
          await fetchUserInfo();
        }
      }
    } catch (err) {
      setError(err.message || 'Failed to switch organization');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateOrg = async (e) => {
    e.preventDefault();
    if (!newOrgName.trim()) return;
    
    setLoading(true);
    setError(null);
    try {
      const response = await createOrganization(newOrgName.trim());
      if (response.success) {
        // If a new token was returned, it's already saved in createOrganization
        // Refresh user info to get updated organizations
        if (fetchUserInfo) {
          await fetchUserInfo();
        } else {
          window.location.reload();
        }
        setShowCreateModal(false);
        setNewOrgName('');
      }
    } catch (err) {
      setError(err.message || 'Failed to create organization');
    } finally {
      setLoading(false);
    }
  };

  // if (!organizations || organizations.length === 0) {
  //   return (
  //     <div style={{ marginBottom: '1rem' }}>
  //       <div className="alert" style={{ 
  //         background: '#fff8e1', 
  //         borderColor: '#ffc107', 
  //         color: '#856404',
  //         padding: '1rem',
  //         borderRadius: '10px',
  //       }}>
  //         <p style={{ margin: '0 0 0.75rem', fontWeight: 600 }}>No organizations available</p>
  //         <p style={{ margin: '0 0 0.75rem', fontSize: '0.9rem' }}>
  //           Create your first organization to get started.
  //         </p>
  //         <button
  //           onClick={() => setShowCreateModal(true)}
  //           className="upload-button"
  //           style={{ marginTop: '0.5rem' }}
  //         >
  //           <span aria-hidden>＋</span>
  //           Create Organization
  //         </button>
  //       </div>

  //       {showCreateModal && (
  //         <div style={{
  //           position: 'fixed',
  //           top: 0,
  //           left: 0,
  //           right: 0,
  //           bottom: 0,
  //           background: 'rgba(0,0,0,0.5)',
  //           display: 'flex',
  //           alignItems: 'center',
  //           justifyContent: 'center',
  //           zIndex: 1000,
  //         }}>
  //           <div style={{
  //             background: 'white',
  //             padding: '2rem',
  //             borderRadius: '8px',
  //             maxWidth: '400px',
  //             width: '90%',
  //           }}>
  //             <h3>Create Organization</h3>
  //             {error && (
  //               <div style={{ padding: '0.5rem', background: '#fee', color: '#c33', marginBottom: '1rem', borderRadius: '4px' }}>
  //                 {error}
  //               </div>
  //             )}
  //             <form onSubmit={handleCreateOrg}>
  //               <div style={{ marginBottom: '1rem' }}>
  //                 <label style={{ display: 'block', marginBottom: '0.5rem' }}>Organization Name</label>
  //                 <input
  //                   type="text"
  //                   value={newOrgName}
  //                   onChange={(e) => setNewOrgName(e.target.value)}
  //                   required
  //                   style={{ width: '100%', padding: '0.5rem', border: '1px solid #ddd', borderRadius: '4px' }}
  //                 />
  //               </div>
  //               <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
  //                 <button
  //                   type="button"
  //                   onClick={() => {
  //                     setShowCreateModal(false);
  //                     setNewOrgName('');
  //                     setError(null);
  //                   }}
  //                   style={{ padding: '0.5rem 1rem', cursor: 'pointer' }}
  //                 >
  //                   Cancel
  //                 </button>
  //                 <button
  //                   type="submit"
  //                   disabled={loading}
  //                   style={{ padding: '0.5rem 1rem', background: '#2563eb', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
  //                 >
  //                   {loading ? 'Creating...' : 'Create'}
  //                 </button>
  //               </div>
  //             </form>
  //           </div>
  //         </div>
  //       )}
  //     </div>
  //   );
  // }

  return (
    <div className="org-switcher">
      <select
        value={currentOrganization?.id || ''}
        onChange={(e) => handleSwitch(e.target.value)}
        disabled={loading}
        className="org-switcher-select"
      >
        <option value="">Select Organization</option>
        {organizations.map((org) => (
          <option key={org.id} value={org.id}>
            {org.name}
          </option>
        ))}
      </select>
      {error && (
        <div className="org-switcher-error">{error}</div>
      )}

      {showCreateModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
        }}>
          <div style={{
            background: 'white',
            padding: '2rem',
            borderRadius: '8px',
            maxWidth: '400px',
            width: '90%',
          }}>
            <h3>Create Organization</h3>
            {error && (
              <div style={{ padding: '0.5rem', background: '#fee', color: '#c33', marginBottom: '1rem', borderRadius: '4px' }}>
                {error}
              </div>
            )}
            <form onSubmit={handleCreateOrg}>
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', marginBottom: '0.5rem' }}>Organization Name</label>
                <input
                  type="text"
                  value={newOrgName}
                  onChange={(e) => setNewOrgName(e.target.value)}
                  required
                  style={{ width: '100%', padding: '0.5rem', border: '1px solid #ddd', borderRadius: '4px' }}
                />
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  onClick={() => {
                    setShowCreateModal(false);
                    setNewOrgName('');
                    setError(null);
                  }}
                  style={{ padding: '0.5rem 1rem', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  style={{ padding: '0.5rem 1rem', background: '#2563eb', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
                >
                  {loading ? 'Creating...' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default OrganizationSwitcher;

