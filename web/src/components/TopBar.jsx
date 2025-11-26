import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import OrganizationSwitcher from './OrganizationSwitcher';

function TopBar() {
  const { user, logout, isAdmin } = useAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const navigate = useNavigate();
  const menuRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setShowUserMenu(false);
      }
    };

    if (showUserMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showUserMenu]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <header className="topbar">
      <div className="topbar-left">
        {!isAdmin && <OrganizationSwitcher />}
      </div>
      
      <div className="topbar-right">
        <div className="topbar-user-menu" ref={menuRef}>
          <button
            className="topbar-user-btn"
            onClick={() => setShowUserMenu(!showUserMenu)}
          >
            <div className="topbar-user-avatar">
              {user?.username?.charAt(0).toUpperCase() || 'U'}
            </div>
            <div className="topbar-user-info">
              <div className="topbar-user-name">{user?.username || 'User'}</div>
              <div className="topbar-user-email">{user?.email || user?.username || 'user@example.com'}</div>
            </div>
            <span className="topbar-user-chevron">▼</span>
          </button>
          
          {showUserMenu && (
            <div className="topbar-user-dropdown">
              <button className="topbar-user-dropdown-item" onClick={handleLogout}>
                Logout
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

export default TopBar;

