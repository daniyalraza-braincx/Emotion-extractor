import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

function Sidebar() {
  const location = useLocation();
  const { isAdmin } = useAuth();

  const navigationItems = [
    { path: '/', label: 'Overview', icon: '📊' },
    { path: '/analysis', label: 'Session Analysis', icon: '📈' },
    ...(isAdmin ? [{ path: '/admin', label: 'Admin Portal', icon: '⚙️' }] : []),
    { path: '/organizations', label: 'Settings', icon: '⚙️' },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">🧠</div>
          <div className="sidebar-logo-text">
            <div className="sidebar-logo-title">BrainCX AI</div>
            <div className="sidebar-logo-subtitle">AI Dashboard</div>
          </div>
        </div>
      </div>
      
      <nav className="sidebar-nav">
        {navigationItems.map((item) => {
          const isActive = location.pathname === item.path || 
            (item.path === '/' && location.pathname === '/dashboard');
          
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`sidebar-nav-item ${isActive ? 'sidebar-nav-item--active' : ''}`}
            >
              <span className="sidebar-nav-icon">{item.icon}</span>
              <span className="sidebar-nav-label">{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}

export default Sidebar;

