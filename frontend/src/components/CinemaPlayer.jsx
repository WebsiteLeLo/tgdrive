import React, { useState, useRef, useEffect } from 'react';
import { 
  Play, Pause, RotateCcw, RotateCw, Volume2, VolumeX, 
  Maximize, Minimize, PictureInPicture, Settings 
} from 'lucide-react';
import { formatTime } from '../utils';

export default function CinemaPlayer({ src, poster, title, onEnded }) {
  const videoRef = useRef(null);
  const containerRef = useRef(null);
  const controlsTimeoutRef = useRef(null);

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [showSpeedMenu, setShowSpeedMenu] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const [hoverTime, setHoverTime] = useState(null);
  const [hoverPos, setHoverPos] = useState(0);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const onTimeUpdate = () => {
      setCurrentTime(video.currentTime);
      if (video.buffered.length > 0) {
        try {
          const end = video.buffered.end(video.buffered.length - 1);
          setBuffered((end / video.duration) * 100);
        } catch (e) {}
      }
    };

    const onLoadedMetadata = () => {
      setDuration(video.duration || 0);
    };

    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);

    video.addEventListener('timeupdate', onTimeUpdate);
    video.addEventListener('loadedmetadata', onLoadedMetadata);
    video.addEventListener('play', onPlay);
    video.addEventListener('pause', onPause);
    if (onEnded) video.addEventListener('ended', onEnded);

    return () => {
      video.removeEventListener('timeupdate', onTimeUpdate);
      video.removeEventListener('loadedmetadata', onLoadedMetadata);
      video.removeEventListener('play', onPlay);
      video.removeEventListener('pause', onPause);
      if (onEnded) video.removeEventListener('ended', onEnded);
    };
  }, [src, onEnded]);

  // Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
      const video = videoRef.current;
      if (!video) return;

      if (e.key === ' ' || e.key === 'k') {
        e.preventDefault();
        togglePlay();
      } else if (e.key === 'ArrowLeft' || e.key === 'j') {
        e.preventDefault();
        skip(-10);
      } else if (e.key === 'ArrowRight' || e.key === 'l') {
        e.preventDefault();
        skip(10);
      } else if (e.key === 'm') {
        e.preventDefault();
        toggleMute();
      } else if (e.key === 'f') {
        e.preventDefault();
        toggleFullscreen();
      } else if (e.key === 'p') {
        e.preventDefault();
        togglePip();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isPlaying, isMuted, isFullscreen]);

  const togglePlay = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      video.play().catch(() => {});
    } else {
      video.pause();
    }
  };

  const skip = (secs) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = Math.max(0, Math.min(video.duration || 0, video.currentTime + secs));
    triggerControls();
  };

  const toggleMute = () => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !isMuted;
    setIsMuted(!isMuted);
  };

  const handleVolumeChange = (e) => {
    const val = parseFloat(e.target.value);
    const video = videoRef.current;
    if (!video) return;
    video.volume = val;
    setVolume(val);
    setIsMuted(val === 0);
  };

  const setSpeed = (spd) => {
    const video = videoRef.current;
    if (!video) return;
    video.playbackRate = spd;
    setPlaybackSpeed(spd);
    setShowSpeedMenu(false);
  };

  const togglePip = async () => {
    const video = videoRef.current;
    if (!video) return;
    try {
      if (document.pictureInPictureElement) {
        await document.exitPictureInPicture();
      } else {
        await video.requestPictureInPicture();
      }
    } catch (e) {}
  };

  const toggleFullscreen = () => {
    const container = containerRef.current;
    if (!container) return;
    if (!document.fullscreenElement) {
      container.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  };

  const handleSeek = (e) => {
    const video = videoRef.current;
    const rect = e.currentTarget.getBoundingClientRect();
    const pos = (e.clientX - rect.left) / rect.width;
    video.currentTime = pos * (video.duration || 0);
  };

  const handleMouseMoveTimeline = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    setHoverPos(pos * 100);
    setHoverTime(pos * (duration || 0));
  };

  const triggerControls = () => {
    setShowControls(true);
    clearTimeout(controlsTimeoutRef.current);
    if (isPlaying) {
      controlsTimeoutRef.current = setTimeout(() => {
        setShowControls(false);
        setShowSpeedMenu(false);
      }, 3000);
    }
  };

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div 
      ref={containerRef}
      onMouseMove={triggerControls}
      onMouseLeave={() => isPlaying && setShowControls(false)}
      className="relative w-full aspect-video bg-black rounded-2xl overflow-hidden shadow-2xl border border-white/10 group select-none"
    >
      <video
        ref={videoRef}
        src={src}
        poster={poster}
        playsInline
        preload="metadata"
        onClick={togglePlay}
        className="w-full h-full object-contain cursor-pointer"
      />

      {/* Big Play Overlay when Paused */}
      {!isPlaying && (
        <button 
          onClick={togglePlay}
          className="absolute inset-0 m-auto w-20 h-20 rounded-full bg-sky-500/90 text-slate-950 flex items-center justify-center shadow-lg shadow-sky-500/40 hover:scale-110 active:scale-95 transition-all duration-200"
          title="Play Lecture"
        >
          <Play className="w-9 h-9 fill-current ml-1" />
        </button>
      )}

      {/* Gradient Bottom Controls */}
      <div className={`absolute inset-x-0 bottom-0 pt-16 pb-4 px-6 bg-gradient-to-t from-black/95 via-black/60 to-transparent transition-opacity duration-300 ${showControls ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}>
        {/* Timeline Slider */}
        <div 
          onClick={handleSeek}
          onMouseMove={handleMouseMoveTimeline}
          onMouseLeave={() => setHoverTime(null)}
          className="relative h-2 w-full bg-white/20 rounded-full cursor-pointer group/timeline mb-4 transition-all hover:h-3"
        >
          {/* Buffered Track */}
          <div 
            style={{ width: `${buffered}%` }} 
            className="absolute top-0 left-0 h-full bg-white/30 rounded-full transition-all duration-300" 
          />
          {/* Played Track */}
          <div 
            style={{ width: `${progressPercent}%` }} 
            className="absolute top-0 left-0 h-full bg-gradient-to-r from-sky-400 to-indigo-500 rounded-full relative"
          >
            <div className="absolute right-0 top-1/2 -translate-y-1/2 w-4 h-4 rounded-full bg-white shadow-md scale-0 group-hover/timeline:scale-100 transition-transform" />
          </div>

          {/* Hover Time Tooltip */}
          {hoverTime !== null && (
            <div 
              style={{ left: `${hoverPos}%` }} 
              className="absolute -top-8 -translate-x-1/2 bg-slate-900/90 border border-white/20 text-white text-xs font-mono px-2 py-0.5 rounded shadow pointer-events-none"
            >
              {formatTime(hoverTime)}
            </div>
          )}
        </div>

        {/* Controls Row */}
        <div className="flex items-center justify-between text-white">
          <div className="flex items-center gap-3">
            <button onClick={togglePlay} className="p-2 rounded-lg hover:bg-white/10 transition" title={isPlaying ? "Pause (Space)" : "Play (Space)"}>
              {isPlaying ? <Pause className="w-5 h-5 fill-current" /> : <Play className="w-5 h-5 fill-current" />}
            </button>
            <button onClick={() => skip(-10)} className="p-2 rounded-lg hover:bg-white/10 transition text-slate-300 hover:text-white" title="Rewind 10s (Left Arrow)">
              <RotateCcw className="w-5 h-5" />
            </button>
            <button onClick={() => skip(10)} className="p-2 rounded-lg hover:bg-white/10 transition text-slate-300 hover:text-white" title="Forward 10s (Right Arrow)">
              <RotateCw className="w-5 h-5" />
            </button>

            {/* Volume Control */}
            <div className="flex items-center gap-2 group/volume ml-1">
              <button onClick={toggleMute} className="p-2 rounded-lg hover:bg-white/10 transition text-slate-300 hover:text-white" title="Mute/Unmute (M)">
                {isMuted || volume === 0 ? <VolumeX className="w-5 h-5" /> : <Volume2 className="w-5 h-5" />}
              </button>
              <input 
                type="range" 
                min="0" 
                max="1" 
                step="0.05"
                value={isMuted ? 0 : volume}
                onChange={handleVolumeChange}
                className="w-16 h-1.5 bg-white/20 accent-sky-400 rounded-full cursor-pointer transition-all"
              />
            </div>

            {/* Elapsed / Total Time */}
            <div className="text-xs font-mono text-slate-300 ml-2">
              <span className="text-white font-medium">{formatTime(currentTime)}</span>
              <span className="mx-1 text-slate-500">/</span>
              <span>{formatTime(duration)}</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Playback Speed Menu */}
            <div className="relative">
              <button 
                onClick={() => setShowSpeedMenu(!showSpeedMenu)} 
                className="px-2.5 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-xs font-semibold text-slate-200 transition"
              >
                {playbackSpeed}x
              </button>
              {showSpeedMenu && (
                <div className="absolute right-0 bottom-full mb-2 bg-slate-900 border border-white/15 rounded-xl py-1 shadow-2xl w-24 text-center z-50 backdrop-blur-md">
                  {[0.5, 0.75, 1, 1.25, 1.5, 1.75, 2].map((spd) => (
                    <button
                      key={spd}
                      onClick={() => setSpeed(spd)}
                      className={`w-full py-1.5 text-xs font-medium hover:bg-sky-500/20 transition ${playbackSpeed === spd ? 'text-sky-400 font-bold bg-sky-500/10' : 'text-slate-300'}`}
                    >
                      {spd}x
                    </button>
                  ))}
                </div>
              )}
            </div>

            <button onClick={togglePip} className="p-2 rounded-lg hover:bg-white/10 transition text-slate-300 hover:text-white" title="Picture in Picture (P)">
              <PictureInPicture className="w-5 h-5" />
            </button>
            <button onClick={toggleFullscreen} className="p-2 rounded-lg hover:bg-white/10 transition text-slate-300 hover:text-white" title="Fullscreen (F)">
              {isFullscreen ? <Minimize className="w-5 h-5" /> : <Maximize className="w-5 h-5" />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
