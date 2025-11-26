import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Sidebar from './Sidebar';
import TopBar from './TopBar';

function Layout({ children }) {
  const { authenticated, isAdmin } = useAuth();
  const location = useLocation();
  
  // Don't show layout on login page
  if (!authenticated || location.pathname === '/login') {
    return <>{children}</>;
  }

  return (
    <div className="app-layout">
      <Sidebar />
      <div className="app-main">
        <TopBar />
        <main className="app-content">
          {children}
        </main>
      </div>
    </div>
  );
}

export default Layout;

