import React, { useState, useEffect } from 'react';
import { ArrowLeft, Share2, Play, Check } from 'lucide-react';
import CinemaPlayer from './CinemaPlayer';
import { formatBytes, getFileTypeInfo } from '../utils';

export default function WatchPage({ token }) {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    async function loadFile() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/f/${encodeURIComponent(token)}`);
        if (!res.ok) throw new Error('Lecture not found or link has expired');
        const data = await res.json();
        setFile(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    loadFile();
  }, [token]);

  const handleCopyLink = () => {
    navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (loading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-[#080c14] text-slate-400">
        <div className="w-10 h-10 border-2 border-sky-500 border-t-transparent rounded-full animate-spin mb-4" />
        <span className="text-sm font-medium tracking-wide">Loading Lecture Stream...</span>
      </div>
    );
  }

  if (error || !file) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-[#080c14] text-slate-200 p-4">
        <div className="bg-[#111726] border border-white/10 rounded-2xl p-8 max-w-md w-full text-center shadow-2xl">
          <h2 className="text-xl font-bold text-white mb-2">Lecture Unavailable</h2>
          <p className="text-sm text-slate-400 mb-6">{error || 'This link has expired or is invalid.'}</p>
          <a href="/" className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-sm transition">
            <ArrowLeft className="w-4 h-4" />
            <span>Return to Series</span>
          </a>
        </div>
      </div>
    );
  }

  const typeInfo = getFileTypeInfo(file.mime_type, file.name);
  const streamUrl = `/stream/${file.message_id}?token=${encodeURIComponent(file.share_token)}`;
  const thumbUrl = `/thumb/${file.message_id}?token=${encodeURIComponent(file.share_token)}`;
  const backUrl = file.folder_token ? `/share/${file.folder_token}` : '/';
  
  const parts = (file.folder || '').split('/').filter(Boolean);
  const chapterName = parts.pop() || 'General';
  const subjectName = parts.pop();
  const displayChapter = subjectName && !subjectName.startsWith('@') && !subjectName.includes('_')
    ? `${subjectName} • ${chapterName}`
    : chapterName;

  // Sibling video lectures for playlist
  const videoSiblings = (file.siblings || []).filter(s => getFileTypeInfo(s.mime_type, s.name).isVideo);

  const handleVideoEnded = () => {
    const currentIdx = videoSiblings.findIndex(s => s.id === file.id);
    if (currentIdx !== -1 && currentIdx + 1 < videoSiblings.length) {
      const nextVideo = videoSiblings[currentIdx + 1];
      window.location.href = `/watch/${encodeURIComponent(nextVideo.share_token)}`;
    }
  };

  // If PDF / Document: Fullscreen clean PDF reader
  if (typeInfo.isPdf) {
    return (
      <div className="min-h-screen flex flex-col bg-[#080c14]">
        {/* Topbar */}
        <div className="h-14 bg-[#0d1322] border-b border-white/10 px-4 flex items-center justify-between gap-4">
          <a href={backUrl} className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-semibold text-slate-300 hover:text-white transition">
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Back to Series</span>
          </a>
          <span className="text-xs sm:text-sm font-semibold text-slate-200 truncate max-w-md">
            {file.name}
          </span>
          <button 
            onClick={handleCopyLink}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-semibold text-slate-300 hover:text-white transition"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Share2 className="w-3.5 h-3.5 text-sky-400" />}
            <span>{copied ? 'Copied' : 'Share'}</span>
          </button>
        </div>
        {/* Native PDF / Stream Frame */}
        <div className="flex-1 w-full bg-slate-950">
          <iframe 
            src={streamUrl} 
            title={file.name}
            className="w-full h-[calc(100vh-56px)] border-none"
          />
        </div>
      </div>
    );
  }

  // Full Cinema Watch Layout for Videos
  return (
    <div className="min-h-screen bg-[#080c14] text-slate-100 flex flex-col">
      {/* Top Navigation */}
      <header className="sticky top-0 z-30 bg-[#080c14]/90 backdrop-blur-md border-b border-white/[0.08] px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        <a 
          href={backUrl} 
          className="inline-flex items-center gap-2 text-xs sm:text-sm font-semibold text-slate-300 hover:text-white px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 transition"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to Series</span>
        </a>

        <div className="flex items-center gap-3">
          <button 
            onClick={handleCopyLink}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-white/10 text-xs font-medium text-slate-200 transition"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Share2 className="w-3.5 h-3.5 text-sky-400" />}
            <span>{copied ? 'Link Copied!' : 'Share Lecture'}</span>
          </button>
        </div>
      </header>

      {/* Main Cinema Content */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8 items-start">
          
          {/* Left Column: Player & Info (8 Cols) */}
          <div className="lg:col-span-8 flex flex-col gap-4">
            <CinemaPlayer 
              src={streamUrl}
              poster={thumbUrl}
              title={file.name}
              onEnded={handleVideoEnded}
            />

            {/* Lecture Meta Box */}
            <div className="bg-[#111726] border border-white/[0.08] rounded-2xl p-5 sm:p-6 flex flex-col gap-3">
              <h1 className="text-base sm:text-xl font-bold text-white tracking-tight leading-snug">
                {file.name}
              </h1>
              
              <div className="flex items-center gap-3 flex-wrap text-xs text-slate-400 pt-2 border-t border-white/[0.06]">
                <span className="bg-sky-500/10 border border-sky-500/20 text-sky-400 px-2.5 py-1 rounded-md font-medium">
                  {displayChapter}
                </span>
                <span>•</span>
                <span className="font-mono">{formatBytes(file.size)}</span>
                <span>•</span>
                <span className="text-slate-400 font-medium">Full HD 1080p Stream</span>
              </div>
            </div>
          </div>

          {/* Right Column: Playlist Sidebar (4 Cols) */}
          <div className="lg:col-span-4 bg-[#111726] border border-white/[0.08] rounded-2xl overflow-hidden flex flex-col max-h-[calc(100vh-140px)] sticky top-20 shadow-xl">
            <div className="p-4 bg-slate-900/80 border-b border-white/[0.06] flex items-center justify-between">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Play className="w-4 h-4 text-sky-400 fill-current" />
                <span>Chapter Lectures</span>
              </h3>
              <span className="text-[11px] font-semibold bg-white/10 text-slate-300 px-2 py-0.5 rounded-full">
                {videoSiblings.length} Episodes
              </span>
            </div>

            <div className="p-3 overflow-y-auto flex flex-col gap-2.5 divide-y divide-white/[0.03]">
              {videoSiblings.map((vf, idx) => {
                const isCurrent = vf.id === file.id;
                const vThumb = `/thumb/${vf.message_id}?token=${encodeURIComponent(vf.share_token)}`;
                return (
                  <a 
                    key={vf.id}
                    href={`/watch/${encodeURIComponent(vf.share_token)}`}
                    className={`pt-2.5 first:pt-0 flex items-center gap-3 p-2 rounded-xl transition ${
                      isCurrent 
                        ? 'bg-sky-500/15 border border-sky-500/40 shadow-sm' 
                        : 'hover:bg-white/5 border border-transparent'
                    }`}
                  >
                    <div className="relative w-20 aspect-video rounded-lg overflow-hidden bg-slate-950 flex-shrink-0">
                      <img 
                        src={vThumb} 
                        alt={vf.name} 
                        loading="lazy"
                        onError={(e) => { e.currentTarget.style.display = 'none'; }}
                        className="w-full h-full object-cover" 
                      />
                    </div>

                    <div className="flex-1 min-w-0">
                      <h4 className={`text-xs font-semibold truncate mb-1 ${isCurrent ? 'text-sky-400 font-bold' : 'text-slate-200'}`}>
                        {vf.name}
                      </h4>
                      <div className="flex items-center gap-2 text-[10.5px] text-slate-400">
                        {isCurrent ? (
                          <span className="text-sky-400 font-bold inline-flex items-center gap-1.5">
                            <span className="flex items-end gap-0.5 h-2.5">
                              <span className="w-0.5 bg-sky-400 rounded-full h-2 animate-eq-1" />
                              <span className="w-0.5 bg-sky-400 rounded-full h-3 animate-eq-2" />
                              <span className="w-0.5 bg-sky-400 rounded-full h-1.5 animate-eq-3" />
                            </span>
                            NOW STREAMING
                          </span>
                        ) : (
                          <>
                            <span>#{idx + 1}</span>
                            <span>•</span>
                            <span className="font-mono">{formatBytes(vf.size)}</span>
                          </>
                        )}
                      </div>
                    </div>
                  </a>
                );
              })}
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}
