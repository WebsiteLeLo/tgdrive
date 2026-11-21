import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import CatalogPage from './components/CatalogPage';
import WatchPage from './components/WatchPage';

export default function App() {
  const [searchQuery, setSearchQuery] = useState('');
  const [route, setRoute] = useState({ type: 'catalog', token: null });

  useEffect(() => {
    const updateRoute = () => {
      const path = window.location.pathname;
      const watchMatch = path.match(/\/(?:watch|v|f|file)\/([^/?#]+)/);
      const shareMatch = path.match(/\/share\/([^/?#]+)/);

      if (watchMatch) {
        setRoute({ type: 'watch', token: watchMatch[1] });
      } else if (shareMatch) {
        setRoute({ type: 'catalog', token: shareMatch[1] });
      } else {
        setRoute({ type: 'catalog', token: null });
      }
    };

    updateRoute();
    window.addEventListener('popstate', updateRoute);

    // Ctrl+K Global Shortcut
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.querySelector('input[type="text"]');
        if (searchInput) searchInput.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);

    return () => {
      window.removeEventListener('popstate', updateRoute);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  if (route.type === 'watch') {
    return <WatchPage token={route.token} />;
  }

  return (
    <div className="min-h-screen bg-[#080c14] text-slate-100 flex flex-col selection:bg-sky-500 selection:text-white">
      <Navbar 
        searchQuery={searchQuery} 
        setSearchQuery={setSearchQuery} 
      />
      <div className="flex-1">
        <CatalogPage 
          shareToken={route.token} 
          searchQuery={searchQuery} 
        />
      </div>
    </div>
  );
}
