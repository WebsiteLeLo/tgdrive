import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Play, FileText, Share2, Check, Layers } from 'lucide-react';
import VideoCard from './VideoCard';
import NoteCard from './NoteCard';
import { getFileTypeInfo, getAdminKey } from '../utils';

const DEFAULT_BATCHES = [
  { id: 'WlrsaUw7NYmPYcAAkY4', name: 'Lakshya JEE 2026', share_token: 'WlrsaUw7NYmPYcAAkY4', file_count: 2271, video_count: 724, note_count: 1547 },
  { id: 'eMzW9H9d-t8xaLhAUlA', name: 'Prayas JEE 2026', share_token: 'eMzW9H9d-t8xaLhAUlA', file_count: 3295, video_count: 989, note_count: 2306 },
  { id: '9pXtLsCIWWnjY4h_bM0', name: 'Mission 100', share_token: '9pXtLsCIWWnjY4h_bM0', file_count: 247, video_count: 105, note_count: 142 },
  { id: 'K92_5DCPSjKbMDexkfA', name: 'Parakarm Gate 2.0 2027', share_token: 'K92_5DCPSjKbMDexkfA', file_count: 243, video_count: 105, note_count: 138 },
  { id: 'SaIxigEXZL2a4PHYRY4', name: 'Ashish Sir Lectures', share_token: 'SaIxigEXZL2a4PHYRY4', file_count: 30, video_count: 12, note_count: 18 },
  { id: 'z49kugBAu5ILsSiC6WQ', name: 'Faisal Sir Lectures', share_token: 'z49kugBAu5ILsSiC6WQ', file_count: 22, video_count: 8, note_count: 14 }
];

export default function CatalogPage({ shareToken, searchQuery }) {
  const [batches, setBatches] = useState(DEFAULT_BATCHES);
  const [activeBatchToken, setActiveBatchToken] = useState(shareToken || 'WlrsaUw7NYmPYcAAkY4');
  const [data, setData] = useState({ files: [], subfolders: [], stats: {}, base_path: '/', folder_name: '' });
  const [currentSection, setCurrentSection] = useState('videos'); // 'videos' or 'notes'
  const [sortBy, setSortBy] = useState('name-asc');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [visibleCount, setVisibleCount] = useState(36);
  const [copied, setCopied] = useState(false);

  const sentinelRef = useRef(null);

  // Sync prop changes
  useEffect(() => {
    if (shareToken && shareToken !== activeBatchToken) {
      setActiveBatchToken(shareToken);
    }
  }, [shareToken]);

  // Fetch live batches from backend
  useEffect(() => {
    async function fetchBatches() {
      try {
        const res = await fetch('/api/batches');
        if (res.ok) {
          const list = await res.json();
          if (Array.isArray(list) && list.length > 0) {
            setBatches(list);
          }
        }
      } catch (e) {
        // Fallback to DEFAULT_BATCHES
      }
    }
    fetchBatches();
  }, []);

  // Fetch materials strictly for the active batch (Batch Isolation)
  useEffect(() => {
    const tokenToLoad = activeBatchToken || shareToken || 'WlrsaUw7NYmPYcAAkY4';
    let isMounted = true;

    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const adminKey = getAdminKey();
        const headers = adminKey ? { 'x-auth': adminKey } : {};
        const url = `/api/share/${encodeURIComponent(tokenToLoad)}?all_files=true`;
        
        const res = await fetch(url, { headers });
        if (!res.ok) throw new Error('Failed to load course materials');
        const json = await res.json();
        if (isMounted) {
          setData(json);
        }
      } catch (err) {
        if (isMounted) {
          setError(err.message);
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }
    fetchData();

    return () => { isMounted = false; };
  }, [activeBatchToken]);

  const handleSwitchBatch = (token) => {
    if (token === activeBatchToken) return;
    setActiveBatchToken(token);
    setVisibleCount(36);
    window.history.pushState(null, '', `/share/${token}`);
  };

  // Separate Videos and Notes in current batch
  const { allVideos, allNotes } = useMemo(() => {
    const vids = [];
    const notes = [];
    (data.files || []).forEach(f => {
      const type = getFileTypeInfo(f.mime_type, f.name);
      if (type.isVideo) vids.push(f);
      else notes.push(f);
    });
    return { allVideos: vids, allNotes: notes };
  }, [data.files]);

  // Search & Sort applied to current section
  const filteredFiles = useMemo(() => {
    let list = currentSection === 'videos' ? allVideos : allNotes;
    const q = (searchQuery || '').trim().toLowerCase();

    // In-memory instant search (<1ms)
    if (q) {
      list = list.filter(f => f.name.toLowerCase().includes(q));
    }

    // Sort
    return [...list].sort((a, b) => {
      if (sortBy === 'name-asc') return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
      if (sortBy === 'name-desc') return b.name.localeCompare(a.name, undefined, { numeric: true, sensitivity: 'base' });
      if (sortBy === 'date-desc') return new Date(b.created_at) - new Date(a.created_at);
      if (sortBy === 'date-asc') return new Date(a.created_at) - new Date(b.created_at);
      if (sortBy === 'size-desc') return b.size - a.size;
      return 0;
    });
  }, [allVideos, allNotes, currentSection, searchQuery, sortBy]);

  // Reset pagination count on filter change
  useEffect(() => {
    setVisibleCount(36);
  }, [searchQuery, currentSection, sortBy, activeBatchToken]);

  // Infinite Scroll IntersectionObserver
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;

    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && visibleCount < filteredFiles.length) {
        setVisibleCount(prev => prev + 36);
      }
    }, { rootMargin: '400px' });

    observer.observe(el);
    return () => observer.disconnect();
  }, [visibleCount, filteredFiles.length]);

  const handleShareSeries = () => {
    const url = `${window.location.origin}/share/${activeBatchToken}`;
    navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const currentBatchMeta = batches.find(b => b.share_token === activeBatchToken);
  const courseTitle = currentBatchMeta?.name || data.folder_name || (data.base_path === '/' ? 'Study Materials' : (data.base_path || '').split('/').filter(Boolean).pop()) || 'Series Portal';
  const visibleBatch = filteredFiles.slice(0, visibleCount);

  if (loading && (!data.files || data.files.length === 0)) {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center text-slate-400">
        <div className="w-10 h-10 border-2 border-sky-500 border-t-transparent rounded-full animate-spin mb-4" />
        <span className="text-sm font-medium tracking-wide">Loading Study Series...</span>
      </div>
    );
  }

  if (error && (!data.files || data.files.length === 0)) {
    return (
      <div className="min-h-[60vh] flex flex-col items-center justify-center text-center p-4">
        <h3 className="text-lg font-bold text-white mb-2">Could Not Load Series</h3>
        <p className="text-sm text-slate-400 max-w-sm mb-4">{error}</p>
        <button onClick={() => window.location.reload()} className="px-4 py-2 bg-sky-500 text-slate-950 rounded-xl text-xs font-semibold cursor-pointer">
          Try Again
        </button>
      </div>
    );
  }

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {/* Batch / Course Series Selector */}
      <div className="mb-6 bg-slate-950/60 border border-white/[0.08] rounded-2xl p-3 sm:p-4">
        <div className="flex items-center justify-between gap-2 mb-2.5">
          <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
            <Layers className="w-3.5 h-3.5 text-sky-400" />
            <span>Select Batch Series</span>
          </div>
          <span className="text-[11px] text-slate-500 hidden sm:inline">
            Each batch is isolated with its own lectures and notes
          </span>
        </div>

        <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-thin">
          {batches.map(b => {
            const isActive = activeBatchToken === b.share_token;
            return (
              <button
                key={b.share_token}
                onClick={() => handleSwitchBatch(b.share_token)}
                className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition-all border cursor-pointer ${
                  isActive
                    ? 'bg-sky-500/20 border-sky-400 text-white shadow-md shadow-sky-500/15 font-bold ring-1 ring-sky-400/40'
                    : 'bg-slate-900/80 border-white/10 text-slate-400 hover:text-white hover:bg-slate-800'
                }`}
              >
                <span>{b.name}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-mono ${
                  isActive ? 'bg-sky-400 text-slate-950 font-bold' : 'bg-white/10 text-slate-400'
                }`}>
                  {b.file_count || 0}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Course Minimalist Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 mb-6 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span className="w-2 h-2 rounded-full bg-sky-400 shadow-sm shadow-sky-400" />
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
              FULL HD 1080P • STUDY CINEMA
            </span>
            <span className="text-[11px] text-slate-500">•</span>
            <span className="text-[11px] font-semibold text-sky-400">
              {data.files.length} Total Items
            </span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
            {courseTitle}
          </h1>
        </div>

        <div className="flex items-center gap-3">
          <button 
            onClick={handleShareSeries}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-white/10 text-xs font-semibold text-slate-200 transition shadow-sm cursor-pointer"
          >
            {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Share2 className="w-4 h-4 text-sky-400" />}
            <span>{copied ? 'Link Copied!' : 'Share Series'}</span>
          </button>

          <select 
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="bg-slate-900 border border-white/10 text-slate-300 text-xs font-medium rounded-xl px-3 py-2 focus:outline-none focus:border-sky-500 cursor-pointer"
          >
            <option value="name-asc">Name (A to Z)</option>
            <option value="name-desc">Name (Z to A)</option>
            <option value="date-desc">Newest First</option>
            <option value="date-asc">Oldest First</option>
            <option value="size-desc">Largest Size</option>
          </select>
        </div>
      </div>

      {/* SEGMENTED SWITCHER: Video Lectures vs Notes & DPPs */}
      <div className="flex items-center justify-between flex-wrap gap-4 mb-6">
        <div className="flex items-center p-1 bg-slate-900/90 border border-white/10 rounded-2xl w-fit shadow-inner">
          <button 
            onClick={() => setCurrentSection('videos')}
            className={`inline-flex items-center gap-2.5 px-5 py-2.5 rounded-xl text-xs sm:text-sm font-bold transition-all cursor-pointer ${
              currentSection === 'videos'
                ? 'bg-gradient-to-r from-sky-500 to-indigo-600 text-white shadow-md shadow-sky-500/25'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <Play className="w-4 h-4 fill-current" />
            <span>Video Lectures</span>
            <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${currentSection === 'videos' ? 'bg-white/20 text-white' : 'bg-white/10 text-slate-400'}`}>
              {allVideos.length}
            </span>
          </button>

          <button 
            onClick={() => setCurrentSection('notes')}
            className={`inline-flex items-center gap-2.5 px-5 py-2.5 rounded-xl text-xs sm:text-sm font-bold transition-all cursor-pointer ${
              currentSection === 'notes'
                ? 'bg-gradient-to-r from-amber-500 to-orange-600 text-slate-950 font-extrabold shadow-md shadow-amber-500/25'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <FileText className="w-4 h-4" />
            <span>Notes & DPPs</span>
            <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${currentSection === 'notes' ? 'bg-slate-950/20 text-slate-950' : 'bg-white/10 text-slate-400'}`}>
              {allNotes.length}
            </span>
          </button>
        </div>

        {/* Counter Info */}
        <span className="text-xs text-slate-400 font-medium">
          Showing {visibleBatch.length} of {filteredFiles.length} {currentSection === 'videos' ? 'Lectures' : 'Notes'}
        </span>
      </div>

      {/* GRID CONTENT */}
      {visibleBatch.length === 0 ? (
        <div className="py-20 text-center bg-[#111726] border border-white/[0.06] rounded-2xl">
          <h3 className="text-base font-bold text-white mb-1">
            No {currentSection === 'videos' ? 'Lectures' : 'Notes'} Found
          </h3>
          <p className="text-xs text-slate-400 max-w-md mx-auto">
            {searchQuery 
              ? `No matches for "${searchQuery}".` 
              : `There are no ${currentSection === 'videos' ? 'video lectures' : 'notes & study materials'} in this batch.`}
          </p>
        </div>
      ) : (
        <div className={currentSection === 'videos' 
          ? "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5 sm:gap-6" 
          : "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
        }>
          {visibleBatch.map(f => (
            currentSection === 'videos' ? (
              <VideoCard key={f.id} file={f} />
            ) : (
              <NoteCard key={f.id} file={f} />
            )
          ))}
        </div>
      )}

      {/* INFINITE SCROLL SENTINEL */}
      <div ref={sentinelRef} className="py-8 flex items-center justify-center text-xs text-slate-500">
        {visibleCount < filteredFiles.length ? (
          <span className="inline-flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
            Loading more {currentSection}...
          </span>
        ) : filteredFiles.length > 0 ? (
          <span>All {filteredFiles.length} {currentSection === 'videos' ? 'lectures' : 'notes'} loaded</span>
        ) : null}
      </div>
    </main>
  );
}
