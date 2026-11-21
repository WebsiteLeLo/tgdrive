import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Play, FileText, Share2, Layers, Check, ArrowRight } from 'lucide-react';
import VideoCard from './VideoCard';
import NoteCard from './NoteCard';
import { getFileTypeInfo } from '../utils';

export default function CatalogPage({ shareToken, searchQuery }) {
  const [data, setData] = useState({ files: [], subfolders: [], stats: {}, base_path: '/', folder_name: '' });
  const [currentFolder, setCurrentFolder] = useState('');
  const [currentSection, setCurrentSection] = useState('videos'); // 'videos' or 'notes'
  const [sortBy, setSortBy] = useState('name-asc');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [visibleCount, setVisibleCount] = useState(36);
  const [copied, setCopied] = useState(false);

  const sentinelRef = useRef(null);

  useEffect(() => {
    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        let url = shareToken 
          ? `/api/share/${encodeURIComponent(shareToken)}?subfolder=${encodeURIComponent(currentFolder)}&all_files=true`
          : `/api/files?folder=${encodeURIComponent(currentFolder || '/')}&all_files=true`;
        
        const res = await fetch(url);
        if (!res.ok) throw new Error('Failed to load course materials');
        const json = await res.json();
        setData(json);
        if (!currentFolder && json.base_path) {
          setCurrentFolder(json.base_path);
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [shareToken, currentFolder]);

  // Separate Videos and Notes
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

  // Filter & Sort
  const filteredFiles = useMemo(() => {
    let list = currentSection === 'videos' ? allVideos : allNotes;
    const q = (searchQuery || '').trim().toLowerCase();

    // In-memory instant search (<1ms)
    if (q) {
      list = list.filter(f => f.name.toLowerCase().includes(q) || f.folder.toLowerCase().includes(q));
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

  // Reset pagination count on search or section change
  useEffect(() => {
    setVisibleCount(36);
  }, [searchQuery, currentSection, currentFolder, sortBy]);

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
    navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const courseTitle = data.folder_name || (currentFolder === '/' ? 'Study Materials' : currentFolder.split('/').filter(Boolean).pop()) || 'Series Portal';
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
        <button onClick={() => window.location.reload()} className="px-4 py-2 bg-sky-500 text-slate-950 rounded-xl text-xs font-semibold">
          Try Again
        </button>
      </div>
    );
  }

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {/* Course Minimalist Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 mb-6 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
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
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-white/10 text-xs font-semibold text-slate-200 transition shadow-sm"
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

      {/* Segmented Section Switcher: Video Lectures vs Notes & DPPs */}
      <div className="flex items-center justify-between flex-wrap gap-4 mb-6">
        <div className="flex items-center p-1 bg-slate-900/90 border border-white/10 rounded-2xl w-fit shadow-inner">
          <button 
            onClick={() => setCurrentSection('videos')}
            className={`inline-flex items-center gap-2.5 px-5 py-2.5 rounded-xl text-xs sm:text-sm font-bold transition-all ${
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
            className={`inline-flex items-center gap-2.5 px-5 py-2.5 rounded-xl text-xs sm:text-sm font-bold transition-all ${
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

      {/* Chapter Filter Pills */}
      {data.subfolders && data.subfolders.length > 0 && (
        <div className="flex items-center gap-2 overflow-x-auto pb-4 mb-6 scrollbar-thin">
          <button 
            onClick={() => setCurrentFolder(data.base_path || '/')}
            className={`px-4 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition border ${
              currentFolder === (data.base_path || '/')
                ? 'bg-sky-500/15 border-sky-500/50 text-sky-400'
                : 'bg-slate-900/60 border-white/5 text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            All Chapters
          </button>

          {data.subfolders.map(sf => {
            const name = sf.split('/').filter(Boolean).pop() || sf;
            const isActive = currentFolder === sf;
            return (
              <button 
                key={sf}
                onClick={() => setCurrentFolder(sf)}
                className={`px-4 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition border ${
                  isActive
                    ? 'bg-sky-500/15 border-sky-500/50 text-sky-400'
                    : 'bg-slate-900/60 border-white/5 text-slate-400 hover:text-white hover:bg-slate-800'
                }`}
              >
                {name}
              </button>
            );
          })}
        </div>
      )}

      {/* Grid Content */}
      {visibleBatch.length === 0 ? (
        <div className="py-20 text-center bg-[#111726] border border-white/[0.06] rounded-2xl">
          <h3 className="text-base font-bold text-white mb-1">
            No {currentSection === 'videos' ? 'Lectures' : 'Notes'} Found
          </h3>
          <p className="text-xs text-slate-400">
            {searchQuery ? `No matches for "${searchQuery}" in this section.` : 'There are no items uploaded to this category yet.'}
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

      {/* Infinite Scroll Sentinel */}
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
