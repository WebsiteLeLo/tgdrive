import React, { useState } from 'react';
import { Play, Search, Share2, Key, Check, X } from 'lucide-react';
import { getAdminKey, setAdminKey } from '../utils';

export default function Navbar({ searchQuery, setSearchQuery }) {
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [adminPassword, setAdminPassword] = useState(getAdminKey());
  const [hasAuth, setHasAuth] = useState(!!getAdminKey());
  const [copied, setCopied] = useState(false);

  const handleShareClick = () => {
    navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSaveAuth = () => {
    setAdminKey(adminPassword);
    setHasAuth(!!adminPassword);
    setShowAuthModal(false);
    window.location.reload();
  };

  return (
    <>
      <header className="sticky top-0 z-40 w-full backdrop-blur-xl bg-[#080c14]/85 border-b border-white/[0.08] transition-all">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
          {/* Logo */}
          <a href="/" className="flex items-center gap-3 group text-decoration-none">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-sky-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20 group-hover:scale-105 transition-transform">
              <Play className="w-5 h-5 text-white fill-current ml-0.5" />
            </div>
            <div>
              <span className="text-base font-bold text-white tracking-tight flex items-center gap-1.5">
                PWX Stream
              </span>
              <span className="text-[10px] uppercase tracking-wider font-semibold text-slate-400 block -mt-1">
                Study Cinema
              </span>
            </div>
          </a>

          {/* Search Bar */}
          <div className="flex-1 max-w-md relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input 
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search lectures, topics, or chapters..."
              className="w-full bg-slate-900/80 border border-white/10 rounded-full pl-10 pr-16 py-2 text-xs sm:text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500/60 focus:ring-1 focus:ring-sky-500/60 transition"
            />
            {searchQuery ? (
              <button 
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            ) : (
              <span className="hidden sm:inline-block absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-mono bg-white/10 text-slate-400 px-1.5 py-0.5 rounded pointer-events-none">
                Ctrl+K
              </span>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 sm:gap-3">
            <button 
              onClick={handleShareClick}
              className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 border border-white/10 text-xs font-medium text-slate-200 transition shadow-sm cursor-pointer"
              title="Share Public Link"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Share2 className="w-3.5 h-3.5 text-sky-400" />}
              <span className="hidden sm:inline">{copied ? 'Link Copied!' : 'Share Series'}</span>
            </button>

            <button 
              onClick={() => setShowAuthModal(true)}
              className={`p-2 rounded-xl border text-xs transition ${
                hasAuth 
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' 
                  : 'bg-slate-800/80 border-white/10 text-slate-400 hover:text-white'
              }`}
              title={hasAuth ? "Admin Key Active" : "Enter Admin Key"}
            >
              {hasAuth ? <Check className="w-4 h-4" /> : <Key className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </header>

      {/* Admin Key Modal */}
      {showAuthModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="bg-slate-900 border border-white/15 rounded-2xl max-w-sm w-full p-6 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Key className="w-4 h-4 text-sky-400" />
                Admin Authentication
              </h3>
              <button onClick={() => setShowAuthModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-xs text-slate-400 mb-4">
              Enter the admin password to unlock management privileges.
            </p>
            <input 
              type="password"
              value={adminPassword}
              onChange={(e) => setAdminPassword(e.target.value)}
              placeholder="Enter password..."
              className="w-full bg-slate-950 border border-white/15 rounded-xl px-4 py-2.5 text-sm text-white mb-5 focus:outline-none focus:border-sky-500"
              onKeyDown={(e) => e.key === 'Enter' && handleSaveAuth()}
            />
            <div className="flex items-center justify-end gap-2">
              <button 
                onClick={() => setShowAuthModal(false)}
                className="px-4 py-2 rounded-xl text-xs font-medium text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button 
                onClick={handleSaveAuth}
                className="px-4 py-2 rounded-xl text-xs font-semibold bg-sky-500 hover:bg-sky-400 text-slate-950 shadow-md shadow-sky-500/20"
              >
                Save Key
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
