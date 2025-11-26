import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { listUsers, createUser, updateUser, deleteUser, listAllOrganizations } from '../services/api';
import '../App.css';

function AdminPortal() {
  const { user, isAdmin } = useAuth();
  const [activeTab, setActiveTab] = useState('users');
  const [users, setUsers] = useState([]);
  const [organizations, setOrganizations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [pagination, setPagination] = useState({
    page: 1,
    per_page: 15,
    total: 0,
    total_pages: 1,
    has_next: false,
    has_prev: false,
  });

  // User management state
  const [showCreateUserModal, setShowCreateUserModal] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [userForm, setUserForm] = useState({
    username: '',
    password: '',
    email: '',
    role: 'user',
  });
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    if (isAdmin) {
      loadUsers();
      loadOrganizations();
    }
  }, [isAdmin, pagination.page]);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await listUsers(pagination.page, pagination.per_page);
      if (response.success) {
        setUsers(response.users || []);
        setPagination(response.pagination || pagination);
      }
    } catch (err) {
      setError(err.message || 'Failed to load users');
    } finally {
      setLoading(false);
    }
  }, [pagination.page, pagination.per_page]);

  const loadOrganizations = useCallback(async () => {
    try {
      const response = await listAllOrganizations(1, 100);
      if (response.success) {
        setOrganizations(response.organizations || []);
      }
    } catch (err) {
      console.error('Failed to load organizations:', err);
    }
  }, []);

  const handleCreateUser = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      const response = await createUser(userForm);
      if (response.success) {
        setShowCreateUserModal(false);
        setUserForm({ username: '', password: '', email: '', role: 'user' });
        loadUsers();
      }
    } catch (err) {
      setError(err.message || 'Failed to create user');
    }
  };

  const handleUpdateUser = async (userId) => {
    setError(null);
    try {
      const updateData = { ...userForm };
      if (!updateData.password) {
        delete updateData.password;
      }
      const response = await updateUser(userId, updateData);
      if (response.success) {
        setEditingUser(null);
        setUserForm({ username: '', password: '', email: '', role: 'user' });
        loadUsers();
      }
    } catch (err) {
      setError(err.message || 'Failed to update user');
    }
  };

  const handleDeleteUser = async (userId) => {
    if (!window.confirm('Are you sure you want to deactivate this user? This action can be reversed later.')) {
      return;
    }
    setError(null);
    try {
      const response = await deleteUser(userId);
      if (response.success) {
        loadUsers();
      }
    } catch (err) {
      setError(err.message || 'Failed to deactivate user');
    }
  };

  const startEditUser = (user) => {
    setEditingUser(user);
    setUserForm({
      username: user.username,
      password: '',
      email: user.email || '',
      role: user.role,
    });
  };

  const filteredUsers = users.filter((u) => {
    if (!searchQuery.trim()) return true;
    const query = searchQuery.toLowerCase();
    return (
      u.username?.toLowerCase().includes(query) ||
      u.email?.toLowerCase().includes(query) ||
      u.role?.toLowerCase().includes(query)
    );
  });

  if (!isAdmin) {
    return (
      <div className="app-root">
        <div className="page-container">
          <div className="analysis-state-card analysis-state-card--error">
            <h2 style={{ margin: 0, color: '#c1324b' }}>Access Denied</h2>
            <p style={{ margin: '0.5rem 0 0', color: '#c1324b' }}>
              You must be an administrator to access this page.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app-root">
      <div className="page-container">
        <header className="calls-header">
          <div className="calls-header__title">
            <h1>Admin Portal</h1>
            <p>Manage users and organizations</p>
          </div>
        </header>

        {error && (
          <div className="alert alert-error">
            {error}
          </div>
        )}

        {/* Tabs */}
        <div className="analysis-tabs">
          <button
            type="button"
            className={`analysis-tab ${activeTab === 'users' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('users')}
          >
            Users
          </button>
          <button
            type="button"
            className={`analysis-tab ${activeTab === 'organizations' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('organizations')}
          >
            Organizations
          </button>
        </div>

        {/* Users Tab */}
        {activeTab === 'users' && (
          <section className="calls-table-card">
            <div className="calls-table-header">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
                <h2 style={{ margin: 0, fontSize: '1.25rem', color: '#1a1f36' }}>User Management</h2>
                <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                  <div className="calls-search">
                    <span aria-hidden className="calls-search__icon">🔍</span>
                    <input
                      type="search"
                      placeholder="Search users..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                    />
                  </div>
                  <button
                    type="button"
                    className="upload-button"
                    onClick={() => {
                      setEditingUser(null);
                      setUserForm({ username: '', password: '', email: '', role: 'user' });
                      setShowCreateUserModal(true);
                    }}
                  >
                    <span aria-hidden>＋</span>
                    Create User
                  </button>
                </div>
              </div>
            </div>

            <div className="calls-table-body">
              {loading ? (
                <div className="call-empty">
                  <div className="spinner" style={{ margin: '0 auto 1rem' }}></div>
                  Loading users...
                </div>
              ) : filteredUsers.length === 0 ? (
                <div className="call-empty">
                  {searchQuery ? `No users match "${searchQuery}"` : 'No users found. Create your first user to get started.'}
                </div>
              ) : (
                filteredUsers.map((u) => (
                  <article key={u.id} className="calls-table-row" style={{ gridTemplateColumns: '1fr 1fr 120px 120px 140px' }}>
                    <div className="calls-table-cell">
                      <span className="cell-primary">{u.username}</span>
                      {u.email && <span className="cell-secondary">{u.email}</span>}
                    </div>
                    <div className="calls-table-cell">
                      <span className="cell-primary">{u.email || '—'}</span>
                    </div>
                    <div className="calls-table-cell">
                      <span className={`status-pill status-${u.role === 'admin' ? 'completed' : 'pending'}`}>
                        {u.role}
                      </span>
                    </div>
                    <div className="calls-table-cell">
                      <span className={`status-pill ${u.is_active ? 'status-completed' : 'status-blocked'}`}>
                        {u.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </div>
                    <div className="calls-table-cell calls-table-cell--actions">
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button
                          type="button"
                          className="row-action"
                          onClick={() => startEditUser(u)}
                        >
                          Edit
                        </button>
                        {u.is_active && (
                          <button
                            type="button"
                            className="row-action"
                            onClick={() => handleDeleteUser(u.id)}
                            style={{ color: '#d64545', borderColor: '#ffced3' }}
                          >
                            Deactivate
                          </button>
                        )}
                      </div>
                    </div>
                  </article>
                ))
              )}
            </div>

            {pagination.total_pages > 1 && (
              <div className="calls-pagination">
                <div className="calls-pagination__info">
                  Showing {((pagination.page - 1) * pagination.per_page) + 1}–{Math.min(pagination.page * pagination.per_page, pagination.total)} of {pagination.total} users
                </div>
                <div className="calls-pagination__controls">
                  <button
                    type="button"
                    className="pagination-button"
                    onClick={() => setPagination({ ...pagination, page: pagination.page - 1 })}
                    disabled={!pagination.has_prev}
                  >
                    Previous
                  </button>
                  <div className="pagination-pages">
                    {Array.from({ length: pagination.total_pages }, (_, i) => i + 1).map((pageNum) => {
                      const showPage = pageNum === 1 || 
                                       pageNum === pagination.total_pages || 
                                       (pageNum >= pagination.page - 1 && pageNum <= pagination.page + 1);
                      
                      if (!showPage && pageNum === pagination.page - 2 && pageNum > 2) {
                        return <span key={`ellipsis-start-${pageNum}`} className="pagination-ellipsis">…</span>;
                      }
                      if (!showPage && pageNum === pagination.page + 2 && pageNum < pagination.total_pages - 1) {
                        return <span key={`ellipsis-end-${pageNum}`} className="pagination-ellipsis">…</span>;
                      }
                      
                      if (!showPage) return null;
                      
                      return (
                        <button
                          key={pageNum}
                          type="button"
                          className={`pagination-button pagination-button--page ${pagination.page === pageNum ? 'pagination-button--active' : ''}`}
                          onClick={() => setPagination({ ...pagination, page: pageNum })}
                        >
                          {pageNum}
                        </button>
                      );
                    })}
                  </div>
                  <button
                    type="button"
                    className="pagination-button"
                    onClick={() => setPagination({ ...pagination, page: pagination.page + 1 })}
                    disabled={!pagination.has_next}
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </section>
        )}

        {/* Organizations Tab */}
        {activeTab === 'organizations' && (
          <section className="calls-table-card">
            <div className="calls-table-header">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
                <h2 style={{ margin: 0, fontSize: '1.25rem', color: '#1a1f36' }}>All Organizations</h2>
                <p style={{ margin: 0, fontSize: '0.85rem', color: '#5c6478' }}>
                  Webhook URL format: <code style={{ background: '#f0f3ff', padding: '0.2rem 0.4rem', borderRadius: '4px', fontSize: '0.8rem' }}>/{'{'}org_id{'}'}/retell/webhook</code>
                </p>
              </div>
            </div>

            <div className="calls-table-body">
              {loading ? (
                <div className="call-empty">
                  <div className="spinner" style={{ margin: '0 auto 1rem' }}></div>
                  Loading organizations...
                </div>
              ) : organizations.length === 0 ? (
                <div className="call-empty">No organizations found.</div>
              ) : (
                organizations.map((org) => (
                  <article key={org.id} className="calls-table-row" style={{ gridTemplateColumns: '2fr 1.5fr 120px 120px 140px' }}>
                    <div className="calls-table-cell">
                      <span className="cell-primary">{org.name}</span>
                      <span className="cell-secondary">
                        ID: {org.id}
                        {org.created_at && ` • Created ${new Date(org.created_at).toLocaleDateString()}`}
                      </span>
                    </div>
                    <div className="calls-table-cell">
                      <span className="cell-primary">{org.owner?.username || 'Unknown'}</span>
                      <span className="cell-secondary">Owner</span>
                    </div>
                    <div className="calls-table-cell">
                      <span className="cell-primary">{org.member_count || 0}</span>
                      <span className="cell-secondary">Members</span>
                    </div>
                    <div className="calls-table-cell">
                      <span className="cell-primary">{org.call_count || 0}</span>
                      <span className="cell-secondary">Calls</span>
                    </div>
                    <div className="calls-table-cell">
                      <span className="cell-secondary">
                        {org.created_at ? new Date(org.created_at).toLocaleDateString() : '—'}
                      </span>
                    </div>
                  </article>
                ))
              )}
            </div>
          </section>
        )}

        {/* Create/Edit User Modal */}
        {(showCreateUserModal || editingUser) && (
          <div
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              background: 'rgba(15, 31, 60, 0.6)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 1000,
              padding: '1rem',
            }}
            onClick={(e) => {
              if (e.target === e.currentTarget) {
                setShowCreateUserModal(false);
                setEditingUser(null);
                setUserForm({ username: '', password: '', email: '', role: 'user' });
              }
            }}
          >
            <div
              className="analysis-summary-panel"
              style={{
                maxWidth: '500px',
                width: '100%',
                maxHeight: '90vh',
                overflowY: 'auto',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <h2 style={{ margin: '0 0 1.5rem', color: '#111a3a' }}>
                {editingUser ? 'Edit User' : 'Create User'}
              </h2>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (editingUser) {
                    handleUpdateUser(editingUser.id);
                  } else {
                    handleCreateUser(e);
                  }
                }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                  <div>
                    <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600, color: '#1a1f36' }}>
                      Username
                    </label>
                    <input
                      type="text"
                      value={userForm.username}
                      onChange={(e) => setUserForm({ ...userForm, username: e.target.value })}
                      required
                      className="calls-search"
                      style={{ width: '100%', maxWidth: 'none', padding: '0.75rem 1rem' }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600, color: '#1a1f36' }}>
                      Password {editingUser && <span style={{ fontWeight: 400, color: '#5c6478', fontSize: '0.9rem' }}>(leave blank to keep current)</span>}
                    </label>
                    <input
                      type="password"
                      value={userForm.password}
                      onChange={(e) => setUserForm({ ...userForm, password: e.target.value })}
                      required={!editingUser}
                      className="calls-search"
                      style={{ width: '100%', maxWidth: 'none', padding: '0.75rem 1rem' }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600, color: '#1a1f36' }}>
                      Email
                    </label>
                    <input
                      type="email"
                      value={userForm.email}
                      onChange={(e) => setUserForm({ ...userForm, email: e.target.value })}
                      className="calls-search"
                      style={{ width: '100%', maxWidth: 'none', padding: '0.75rem 1rem' }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600, color: '#1a1f36' }}>
                      Role
                    </label>
                    <select
                      value={userForm.role}
                      onChange={(e) => setUserForm({ ...userForm, role: e.target.value })}
                      className="calls-search"
                      style={{ width: '100%', maxWidth: 'none', padding: '0.75rem 1rem', cursor: 'pointer' }}
                    >
                      <option value="user">User</option>
                      <option value="admin">Admin</option>
                    </select>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '2rem' }}>
                  <button
                    type="button"
                    className="toolbar-chip"
                    onClick={() => {
                      setShowCreateUserModal(false);
                      setEditingUser(null);
                      setUserForm({ username: '', password: '', email: '', role: 'user' });
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="upload-button"
                  >
                    {editingUser ? 'Update User' : 'Create User'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default AdminPortal;
