import React from 'react';
import { Play, ExternalLink } from 'lucide-react';
import { formatBytes } from '../utils';

export default function VideoCard({ file }) {
  const thumbUrl = `/thumb/${file.message_id}?token=${encodeURIComponent(file.share_token)}`;
  const watchUrl = `/watch/${encodeURIComponent(file.share_token)}`;

  return (
    <a 
      href={watchUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="group bg-[#111726] border border-white/[0.08] hover:border-sky-500/50 rounded-2xl overflow-hidden flex flex-col transition-all duration-300 hover:-translate-y-1 hover:shadow-xl hover:shadow-sky-500/10 cursor-pointer"
    >
      {/* 16:9 Thumbnail Stage */}
      <div className="relative aspect-video w-full bg-slate-950 overflow-hidden flex items-center justify-center">
        <img 
          src={thumbUrl} 
          alt={file.name}
          loading="lazy"
          onError={(e) => { e.currentTarget.style.display = 'none'; }}
          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
        />

        {/* Badges */}
        <span className="absolute top-2.5 left-2.5 bg-slate-950/85 border border-white/10 backdrop-blur-md text-[10px] font-bold text-sky-400 px-2 py-0.5 rounded tracking-wider uppercase">
          1080p HD
        </span>
        <span className="absolute bottom-2.5 right-2.5 bg-black/80 backdrop-blur-md text-[11px] font-mono text-slate-200 px-2 py-0.5 rounded">
          {formatBytes(file.size)}
        </span>

        {/* Hover Center Play Button */}
        <div className="absolute inset-0 m-auto w-12 h-12 rounded-full bg-sky-500 text-slate-950 flex items-center justify-center opacity-0 group-hover:opacity-100 scale-75 group-hover:scale-100 transition-all duration-200 shadow-lg shadow-sky-500/40">
          <Play className="w-5 h-5 fill-current ml-0.5" />
        </div>
      </div>

      {/* Info Body */}
      <div className="p-3.5 sm:p-4 flex flex-col flex-1 justify-between gap-3">
        <h4 
          title={file.name}
          className="text-xs sm:text-sm font-semibold text-slate-100 line-clamp-2 group-hover:text-sky-400 transition-colors leading-snug"
        >
          {file.name}
        </h4>

        <div className="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-white/[0.04]">
          <span className="bg-sky-500/10 border border-sky-500/20 px-2 py-0.5 rounded text-[11px] text-sky-400 font-medium">
            Lecture
          </span>
          <span className="inline-flex items-center gap-1 text-slate-400 group-hover:text-sky-400 text-[11px] font-medium transition-colors">
            <span>Watch</span>
            <ExternalLink className="w-3 h-3" />
          </span>
        </div>
      </div>
    </a>
  );
}
