import React from 'react';
import { FileText, ExternalLink } from 'lucide-react';
import { formatBytes, getFileExtension } from '../utils';

export default function NoteCard({ file }) {
  const watchUrl = `/watch/${encodeURIComponent(file.share_token)}`;
  const ext = (getFileExtension(file.name) || 'PDF').toUpperCase();
  const chapterName = file.folder.split('/').filter(Boolean).pop() || 'Notes';

  return (
    <a 
      href={watchUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="group bg-[#111726] border border-white/[0.08] hover:border-amber-500/50 rounded-2xl p-4 sm:p-5 flex items-center gap-4 transition-all duration-300 hover:-translate-y-1 hover:shadow-xl hover:shadow-amber-500/10 cursor-pointer"
    >
      {/* Icon Badge */}
      <div className="w-12 h-12 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400 flex items-center justify-center flex-shrink-0 group-hover:scale-105 group-hover:bg-amber-500 group-hover:text-slate-950 transition-all duration-300">
        <FileText className="w-6 h-6" />
      </div>

      {/* Info Body */}
      <div className="flex-1 min-w-0 pr-2">
        <h4 
          title={file.name}
          className="text-xs sm:text-sm font-semibold text-slate-100 truncate group-hover:text-amber-400 transition-colors mb-1.5"
        >
          {file.name}
        </h4>
        <div className="flex items-center gap-2 text-xs text-slate-400 flex-wrap">
          <span className="bg-white/5 border border-white/[0.06] px-2 py-0.5 rounded text-[11px] text-slate-300 truncate max-w-[150px]">
            {chapterName}
          </span>
          <span>•</span>
          <span className="font-mono text-[11px]">{formatBytes(file.size)}</span>
          <span>•</span>
          <span className="text-[11px] font-semibold text-amber-400/90">{ext}</span>
        </div>
      </div>

      {/* Action Button */}
      <div className="flex-shrink-0">
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 group-hover:bg-amber-500 text-amber-400 group-hover:text-slate-950 text-xs font-semibold transition-all duration-200">
          <span>Open</span>
          <ExternalLink className="w-3.5 h-3.5" />
        </span>
      </div>
    </a>
  );
}
