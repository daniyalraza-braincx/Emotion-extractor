import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import braincxLogo from '../assets/braincx_logo.png';

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
          <img 
            src={braincxLogo} 
            alt="BrainCX Logo" 
            style={{
              height: '40px',
              width: 'auto',
              objectFit: 'contain',
            }}
          />
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

