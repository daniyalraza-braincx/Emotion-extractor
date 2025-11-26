import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { listUsers, createUser, updateUser, deleteUser, getUserOrganizationsAdmin } from '../services/api';
import Card from '../components/Card';
import Button from '../components/Button';
import StatusBadge from '../components/StatusBadge';

function AdminPortal() {
  const { user, isAdmin } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [userOrganizations, setUserOrganizations] = useState({}); // { userId: [organizations] }
  const [loadingUserOrgs, setLoadingUserOrgs] = useState({}); // { userId: true/false }
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

  const loadUserOrganizations = useCallback(async (userId) => {
    if (loadingUserOrgs[userId]) return; // Already loading
    setLoadingUserOrgs(prev => ({ ...prev, [userId]: true }));
    try {
      const response = await getUserOrganizationsAdmin(userId);
      if (response.success) {
        setUserOrganizations(prev => ({ ...prev, [userId]: response.organizations || [] }));
      }
    } catch (err) {
      console.error('Failed to load user organizations:', err);
      setUserOrganizations(prev => ({ ...prev, [userId]: [] }));
    } finally {
      setLoadingUserOrgs(prev => ({ ...prev, [userId]: false }));
    }
  }, [loadingUserOrgs]);

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
    // Load organizations for this user
    loadUserOrganizations(user.id);
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
      <div>
        <Card style={{ background: '#fff6f6', borderColor: '#ffced3', color: '#ca3949' }}>
          <h2 style={{ margin: 0, color: '#ca3949' }}>Access Denied</h2>
          <p style={{ margin: '0.5rem 0 0', color: '#ca3949' }}>
            You must be an administrator to access this page.
          </p>
        </Card>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-header-title">Manage Users</h1>
        </div>
      </div>

      {error && (
        <Card className="mb-3" style={{ background: '#fff6f6', borderColor: '#ffced3', color: '#ca3949' }}>
          {error}
        </Card>
      )}

      {/* Users List */}
      <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--spacing-md)', marginBottom: 'var(--spacing-lg)' }}>
            <h2 style={{ margin: 0, fontSize: 'var(--font-size-xl)', fontWeight: 'var(--font-weight-bold)', color: 'var(--text-primary)' }}>
              User Management
            </h2>
            <div style={{ display: 'flex', gap: 'var(--spacing-sm)', alignItems: 'center', flexWrap: 'wrap' }}>
              <input
                type="search"
                placeholder="Search users..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{
                  padding: 'var(--spacing-sm) var(--spacing-md)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--border-radius)',
                  fontSize: 'var(--font-size-sm)',
                }}
              />
              <Button
                variant="primary"
                icon="+"
                onClick={() => {
                  setEditingUser(null);
                  setUserForm({ username: '', password: '', email: '', role: 'user' });
                  setShowCreateUserModal(true);
                }}
              >
                Create User
              </Button>
            </div>
          </div>

          {loading ? (
            <Card className="text-center" style={{ padding: 'var(--spacing-2xl)' }}>
              <p style={{ color: 'var(--text-secondary)' }}>Loading users...</p>
            </Card>
          ) : filteredUsers.length === 0 ? (
            <Card className="text-center" style={{ padding: 'var(--spacing-2xl)' }}>
              <p style={{ color: 'var(--text-secondary)' }}>
                {searchQuery ? `No users match "${searchQuery}"` : 'No users found. Create your first user to get started.'}
              </p>
            </Card>
          ) : (
            <div className="grid grid-cols-1" style={{ gap: 'var(--spacing-md)' }}>
              {filteredUsers.map((u) => (
                <Card key={u.id} className="user-card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 'var(--spacing-md)' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-sm)', marginBottom: 'var(--spacing-xs)' }}>
                        <h3 style={{ margin: 0, fontSize: 'var(--font-size-lg)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--text-primary)' }}>
                          {u.username}
                        </h3>
                        <StatusBadge status={u.role === 'admin' ? 'active' : 'pending'} label={u.role} />
                        <StatusBadge status={u.is_active ? 'active' : 'offline'} label={u.is_active ? 'Active' : 'Inactive'} />
                      </div>
                      {u.email && (
                        <p style={{ margin: 0, fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)' }}>
                          {u.email}
                        </p>
                      )}
                    </div>
                    <div style={{ display: 'flex', gap: 'var(--spacing-sm)' }}>
                      <Button variant="secondary" size="small" onClick={() => startEditUser(u)}>
                        Edit
                      </Button>
                      {u.is_active && (
                        <Button variant="danger" size="small" onClick={() => handleDeleteUser(u.id)}>
                          Deactivate
                        </Button>
                      )}
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}

          {pagination.total_pages > 1 && (
            <Card className="mt-3" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--spacing-md)' }}>
              <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)' }}>
                Showing {((pagination.page - 1) * pagination.per_page) + 1}–{Math.min(pagination.page * pagination.per_page, pagination.total)} of {pagination.total} users
              </div>
              <div style={{ display: 'flex', gap: 'var(--spacing-sm)', alignItems: 'center' }}>
                <Button
                  variant="secondary"
                  size="small"
                  onClick={() => setPagination({ ...pagination, page: pagination.page - 1 })}
                  disabled={!pagination.has_prev}
                >
                  Previous
                </Button>
                <div style={{ display: 'flex', gap: 'var(--spacing-xs)' }}>
                  {Array.from({ length: pagination.total_pages }, (_, i) => i + 1).map((pageNum) => {
                    const showPage = pageNum === 1 || 
                                     pageNum === pagination.total_pages || 
                                     (pageNum >= pagination.page - 1 && pageNum <= pagination.page + 1);
                    
                    if (!showPage && pageNum === pagination.page - 2 && pageNum > 2) {
                      return <span key={`ellipsis-start-${pageNum}`} style={{ padding: 'var(--spacing-sm)' }}>…</span>;
                    }
                    if (!showPage && pageNum === pagination.page + 2 && pageNum < pagination.total_pages - 1) {
                      return <span key={`ellipsis-end-${pageNum}`} style={{ padding: 'var(--spacing-sm)' }}>…</span>;
                    }
                    
                    if (!showPage) return null;
                    
                    return (
                      <Button
                        key={pageNum}
                        variant={pagination.page === pageNum ? 'primary' : 'secondary'}
                        size="small"
                        onClick={() => setPagination({ ...pagination, page: pageNum })}
                      >
                        {pageNum}
                      </Button>
                    );
                  })}
                </div>
                <Button
                  variant="secondary"
                  size="small"
                  onClick={() => setPagination({ ...pagination, page: pagination.page + 1 })}
                  disabled={!pagination.has_next}
                >
                  Next
                </Button>
              </div>
            </Card>
          )}
        </Card>

      {/* Create/Edit User Modal */}
      {(showCreateUserModal || editingUser) && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: 'var(--spacing-lg)',
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) {
              setShowCreateUserModal(false);
              setEditingUser(null);
              setUserForm({ username: '', password: '', email: '', role: 'user' });
            }
          }}
        >
          <Card
            style={{
              maxWidth: editingUser ? '800px' : '500px',
              width: '100%',
              maxHeight: '90vh',
              overflowY: 'auto',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h2 style={{ margin: '0 0 var(--spacing-lg)', fontSize: 'var(--font-size-xl)', fontWeight: 'var(--font-weight-bold)', color: 'var(--text-primary)' }}>
              {editingUser ? 'Edit User' : 'Create User'}
            </h2>
            {editingUser && (
              <div style={{ marginBottom: 'var(--spacing-lg)', padding: 'var(--spacing-md)', background: 'var(--bg-tertiary)', borderRadius: 'var(--border-radius)' }}>
                <h3 style={{ margin: '0 0 var(--spacing-md)', fontSize: 'var(--font-size-lg)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--text-primary)' }}>
                  User Details
                </h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 'var(--spacing-md)' }}>
                  <div>
                    <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)', marginBottom: 'var(--spacing-xs)' }}>User ID</div>
                    <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--text-primary)' }}>
                      {editingUser.id}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)', marginBottom: 'var(--spacing-xs)' }}>Status</div>
                    <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--text-primary)' }}>
                      {editingUser.is_active ? 'Active' : 'Inactive'}
                    </div>
                  </div>
                  {editingUser.created_at && (
                    <div>
                      <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)', marginBottom: 'var(--spacing-xs)' }}>Created</div>
                      <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--text-primary)' }}>
                        {new Date(editingUser.created_at).toLocaleDateString()}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
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
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-lg)' }}>
                <div>
                  <label style={{
                    display: 'block',
                    marginBottom: 'var(--spacing-xs)',
                    fontSize: 'var(--font-size-sm)',
                    fontWeight: 'var(--font-weight-semibold)',
                    color: 'var(--text-primary)'
                  }}>
                    Username
                  </label>
                  <input
                    type="text"
                    value={userForm.username}
                    onChange={(e) => setUserForm({ ...userForm, username: e.target.value })}
                    required
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
                    Password {editingUser && <span style={{ fontWeight: 400, color: 'var(--text-secondary)', fontSize: 'var(--font-size-xs)' }}>(leave blank to keep current)</span>}
                  </label>
                  <input
                    type="password"
                    value={userForm.password}
                    onChange={(e) => setUserForm({ ...userForm, password: e.target.value })}
                    required={!editingUser}
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
                    Email
                  </label>
                  <input
                    type="email"
                    value={userForm.email}
                    onChange={(e) => setUserForm({ ...userForm, email: e.target.value })}
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
                    Role
                  </label>
                  <select
                    value={userForm.role}
                    onChange={(e) => setUserForm({ ...userForm, role: e.target.value })}
                    style={{
                      width: '100%',
                      padding: 'var(--spacing-sm) var(--spacing-md)',
                      border: '1px solid var(--border-color)',
                      borderRadius: 'var(--border-radius)',
                      fontSize: 'var(--font-size-base)',
                      cursor: 'pointer',
                      background: 'var(--bg-primary)',
                    }}
                  >
                    <option value="user">User</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
              </div>
              {editingUser && (
                <div style={{ marginTop: 'var(--spacing-xl)', paddingTop: 'var(--spacing-xl)', borderTop: '1px solid var(--border-color)' }}>
                  <h3 style={{ margin: '0 0 var(--spacing-md)', fontSize: 'var(--font-size-lg)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--text-primary)' }}>
                    Organizations
                  </h3>
                  {loadingUserOrgs[editingUser.id] ? (
                    <div style={{ padding: 'var(--spacing-lg)', textAlign: 'center', color: 'var(--text-secondary)' }}>
                      Loading organizations...
                    </div>
                  ) : userOrganizations[editingUser.id] && userOrganizations[editingUser.id].length > 0 ? (
                    <div className="grid grid-cols-1" style={{ gap: 'var(--spacing-md)', maxHeight: '300px', overflowY: 'auto' }}>
                      {userOrganizations[editingUser.id].map((org) => (
                        <Card key={org.id} style={{ padding: 'var(--spacing-md)', background: 'var(--bg-tertiary)' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 'var(--spacing-sm)' }}>
                            <div style={{ flex: 1 }}>
                              <div style={{ fontWeight: 'var(--font-weight-semibold)', color: 'var(--text-primary)', fontSize: 'var(--font-size-base)', marginBottom: 'var(--spacing-xs)' }}>
                                {org.name}
                              </div>
                              <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-secondary)' }}>
                                ID: {org.id} • Role: {org.user_role || 'Member'}
                              </div>
                            </div>
                          </div>
                        </Card>
                      ))}
                    </div>
                  ) : (
                    <div style={{ padding: 'var(--spacing-lg)', textAlign: 'center', color: 'var(--text-secondary)' }}>
                      No organizations found for this user.
                    </div>
                  )}
                </div>
              )}
              <div style={{ display: 'flex', gap: 'var(--spacing-sm)', justifyContent: 'flex-end', marginTop: 'var(--spacing-xl)' }}>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    setShowCreateUserModal(false);
                    setEditingUser(null);
                    setUserForm({ username: '', password: '', email: '', role: 'user' });
                    setUserOrganizations({});
                  }}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                >
                  {editingUser ? 'Update User' : 'Create User'}
                </Button>
              </div>
            </form>
          </Card>
        </div>
      )}
    </div>
  );
}

export default AdminPortal;
