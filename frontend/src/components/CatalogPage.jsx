import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Play, FileText, Share2, Check, ChevronRight, X, Sparkles, BookOpen, Atom, Calculator, FlaskConical, ClipboardList } from 'lucide-react';
import VideoCard from './VideoCard';
import NoteCard from './NoteCard';
import { getFileTypeInfo } from '../utils';

export default function CatalogPage({ shareToken, searchQuery }) {
  const [data, setData] = useState({ files: [], subfolders: [], stats: {}, base_path: '/', folder_name: '' });
  const [selectedSubject, setSelectedSubject] = useState('All');
  const [selectedChapter, setSelectedChapter] = useState('All');
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
        const url = shareToken 
          ? `/api/share/${encodeURIComponent(shareToken)}?all_files=true`
          : `/api/files?folder=${encodeURIComponent('/')}&all_files=true`;
        
        const res = await fetch(url);
        if (!res.ok) throw new Error('Failed to load course materials');
        const json = await res.json();
        setData(json);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [shareToken]);

  // Extract Subject and Chapter mappings and counts
  const { subjects, chaptersBySubject, subjectCounts, chapterCounts } = useMemo(() => {
    const subjMap = {};
    const sCounts = { All: (data.files || []).length };
    const cCounts = {};
    const basePath = (data.base_path || '').replace(/\/+$/, '');

    (data.files || []).forEach(f => {
      let rel = f.folder || '';
      if (basePath && rel.startsWith(basePath)) {
        rel = rel.substring(basePath.length);
      }
      const parts = rel.split('/').filter(Boolean);
      const subject = parts[0] || 'General';
      const chapter = parts[1] || 'General Materials';

      if (!subjMap[subject]) {
        subjMap[subject] = new Set();
      }
      subjMap[subject].add(chapter);

      sCounts[subject] = (sCounts[subject] || 0) + 1;
      
      const chKey = `${subject}::${chapter}`;
      cCounts[chKey] = (cCounts[chKey] || 0) + 1;
    });

    const standardOrder = ['Physics', 'Chemistry', 'Mathematics', 'Tests & Guidance'];
    const subjectList = Object.keys(subjMap).sort((a, b) => {
      const idxA = standardOrder.indexOf(a);
      const idxB = standardOrder.indexOf(b);
      if (idxA !== -1 && idxB !== -1) return idxA - idxB;
      if (idxA !== -1) return -1;
      if (idxB !== -1) return 1;
      return a.localeCompare(b);
    });

    const chMap = {};
    subjectList.forEach(s => {
      chMap[s] = Array.from(subjMap[s]).sort((a, b) => a.localeCompare(b));
    });

    return { 
      subjects: subjectList, 
      chaptersBySubject: chMap,
      subjectCounts: sCounts,
      chapterCounts: cCounts
    };
  }, [data.files, data.base_path]);

  // Available chapters for currently selected subject
  const currentChapterList = useMemo(() => {
    if (selectedSubject === 'All') {
      const allChs = new Set();
      Object.values(chaptersBySubject).forEach(list => list.forEach(ch => allChs.add(ch)));
      return Array.from(allChs).sort((a, b) => a.localeCompare(b));
    }
    return chaptersBySubject[selectedSubject] || [];
  }, [selectedSubject, chaptersBySubject]);

  // Filter files by Subject & Chapter first
  const subjectFilteredFiles = useMemo(() => {
    const basePath = (data.base_path || '').replace(/\/+$/, '');
    return (data.files || []).filter(f => {
      let rel = f.folder || '';
      if (basePath && rel.startsWith(basePath)) {
        rel = rel.substring(basePath.length);
      }
      const parts = rel.split('/').filter(Boolean);
      const subject = parts[0] || 'General';
      const chapter = parts[1] || 'General Materials';

      if (selectedSubject !== 'All' && subject !== selectedSubject) {
        return false;
      }
      if (selectedChapter !== 'All' && chapter !== selectedChapter) {
        return false;
      }
      return true;
    });
  }, [data.files, data.base_path, selectedSubject, selectedChapter]);

  // Separate Videos and Notes in current view
  const { allVideos, allNotes } = useMemo(() => {
    const vids = [];
    const notes = [];
    subjectFilteredFiles.forEach(f => {
      const type = getFileTypeInfo(f.mime_type, f.name);
      if (type.isVideo) vids.push(f);
      else notes.push(f);
    });
    return { allVideos: vids, allNotes: notes };
  }, [subjectFilteredFiles]);

  // Search & Sort applied to current section
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

  // Reset pagination count on filter change
  useEffect(() => {
    setVisibleCount(36);
  }, [searchQuery, currentSection, selectedSubject, selectedChapter, sortBy]);

  // Reset chapter selection if subject changes
  const handleSelectSubject = (s) => {
    setSelectedSubject(s);
    setSelectedChapter('All');
  };

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

  const getSubjectIcon = (subj) => {
    switch (subj) {
      case 'Physics': return <Atom className="w-3.5 h-3.5" />;
      case 'Chemistry': return <FlaskConical className="w-3.5 h-3.5" />;
      case 'Mathematics': return <Calculator className="w-3.5 h-3.5" />;
      case 'Tests & Guidance': return <ClipboardList className="w-3.5 h-3.5" />;
      default: return <BookOpen className="w-3.5 h-3.5" />;
    }
  };

  const courseTitle = data.folder_name || (data.base_path === '/' ? 'Study Materials' : (data.base_path || '').split('/').filter(Boolean).pop()) || 'Series Portal';
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

      {/* 1. PRIMARY SUBJECT TABS (Subject Level Navigation) */}
      <div className="mb-4">
        <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2 flex items-center gap-1.5">
          <span>Subjects</span>
        </div>
        <div className="flex items-center gap-2 overflow-x-auto pb-2 scrollbar-thin">
          <button
            onClick={() => handleSelectSubject('All')}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition border cursor-pointer ${
              selectedSubject === 'All'
                ? 'bg-sky-500 text-slate-950 border-sky-400 shadow-md shadow-sky-500/20 font-bold'
                : 'bg-slate-900/80 border-white/10 text-slate-300 hover:text-white hover:bg-slate-800'
            }`}
          >
            <BookOpen className="w-3.5 h-3.5" />
            <span>All Subjects</span>
            <span className={`text-[10px] px-1.5 py-0.2 rounded-full ${selectedSubject === 'All' ? 'bg-slate-950/20 text-slate-950 font-bold' : 'bg-white/10 text-slate-400'}`}>
              {subjectCounts.All || 0}
            </span>
          </button>

          {subjects.map(s => {
            const count = subjectCounts[s] || 0;
            const isActive = selectedSubject === s;
            return (
              <button
                key={s}
                onClick={() => handleSelectSubject(s)}
                className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition border cursor-pointer ${
                  isActive
                    ? 'bg-sky-500 text-slate-950 border-sky-400 shadow-md shadow-sky-500/20 font-bold'
                    : 'bg-slate-900/80 border-white/10 text-slate-300 hover:text-white hover:bg-slate-800'
                }`}
              >
                {getSubjectIcon(s)}
                <span>{s}</span>
                <span className={`text-[10px] px-1.5 py-0.2 rounded-full ${isActive ? 'bg-slate-950/20 text-slate-950 font-bold' : 'bg-white/10 text-slate-400'}`}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* 2. CHAPTER FILTER PILLS (Chapter Level Navigation) */}
      {currentChapterList.length > 0 && (
        <div className="mb-6 bg-slate-950/40 border border-white/[0.06] rounded-2xl p-3 sm:p-4">
          <div className="flex items-center justify-between gap-2 mb-2.5">
            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <span>Chapters {selectedSubject !== 'All' ? `in ${selectedSubject}` : ''}</span>
              <span className="text-slate-500">({currentChapterList.length})</span>
            </div>

            {selectedChapter !== 'All' && (
              <button
                onClick={() => setSelectedChapter('All')}
                className="text-[11px] text-sky-400 hover:text-sky-300 inline-flex items-center gap-1 font-medium cursor-pointer"
              >
                <span>Reset Chapter</span>
                <X className="w-3 h-3" />
              </button>
            )}
          </div>

          <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-thin">
            <button
              onClick={() => setSelectedChapter('All')}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition border cursor-pointer ${
                selectedChapter === 'All'
                  ? 'bg-white/15 border-white/30 text-white font-semibold'
                  : 'bg-slate-900/60 border-white/5 text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`}
            >
              All Chapters
            </button>

            {currentChapterList.map(ch => {
              const isActive = selectedChapter === ch;
              const chCount = selectedSubject !== 'All' 
                ? (chapterCounts[`${selectedSubject}::${ch}`] || 0)
                : Object.keys(chaptersBySubject).reduce((acc, subj) => acc + (chapterCounts[`${subj}::${ch}`] || 0), 0);

              return (
                <button
                  key={ch}
                  onClick={() => setSelectedChapter(ch)}
                  className={`px-3 py-1.5 rounded-lg text-xs whitespace-nowrap transition border cursor-pointer inline-flex items-center gap-1.5 ${
                    isActive
                      ? 'bg-sky-500/20 border-sky-500/60 text-sky-300 font-semibold shadow-sm'
                      : 'bg-slate-900/60 border-white/5 text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                  }`}
                >
                  <span>{ch}</span>
                  {chCount > 0 && (
                    <span className="text-[10px] text-slate-500 font-mono">
                      {chCount}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* 3. ACTIVE NAVIGATION BREADCRUMB */}
      {(selectedSubject !== 'All' || selectedChapter !== 'All') && (
        <div className="flex items-center gap-2 text-xs text-slate-400 mb-5 flex-wrap">
          <span className="text-slate-500">Browsing:</span>
          <button 
            onClick={() => { setSelectedSubject('All'); setSelectedChapter('All'); }}
            className="text-slate-300 hover:text-white underline cursor-pointer"
          >
            All Subjects
          </button>
          
          {selectedSubject !== 'All' && (
            <>
              <ChevronRight className="w-3 h-3 text-slate-600" />
              <button 
                onClick={() => setSelectedChapter('All')}
                className={`cursor-pointer ${selectedChapter === 'All' ? 'text-sky-400 font-semibold' : 'text-slate-300 hover:text-white underline'}`}
              >
                {selectedSubject}
              </button>
            </>
          )}

          {selectedChapter !== 'All' && (
            <>
              <ChevronRight className="w-3 h-3 text-slate-600" />
              <span className="text-sky-400 font-semibold">{selectedChapter}</span>
            </>
          )}

          <button
            onClick={() => { setSelectedSubject('All'); setSelectedChapter('All'); }}
            className="ml-2 inline-flex items-center gap-1 px-2 py-0.5 rounded bg-white/5 hover:bg-white/10 text-[11px] text-slate-300 transition cursor-pointer"
          >
            <span>Clear Filter</span>
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* 4. SEGMENTED SWITCHER: Video Lectures vs Notes & DPPs */}
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

      {/* 5. GRID CONTENT */}
      {visibleBatch.length === 0 ? (
        <div className="py-20 text-center bg-[#111726] border border-white/[0.06] rounded-2xl">
          <h3 className="text-base font-bold text-white mb-1">
            No {currentSection === 'videos' ? 'Lectures' : 'Notes'} Found
          </h3>
          <p className="text-xs text-slate-400 max-w-md mx-auto">
            {searchQuery 
              ? `No matches for "${searchQuery}" in this category.` 
              : `There are no ${currentSection === 'videos' ? 'video lectures' : 'notes & study materials'} for this selection.`}
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

      {/* 6. INFINITE SCROLL SENTINEL */}
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
