/**
 * PipelineProgressPanel — Modal overlay for 1-Click Full Subject Pipeline
 * Starts a background job immediately, then polls /api/admin/pipeline/status/{job_id}
 * every 3 seconds for live progress updates.
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import {
  X, Loader2, CheckCircle2, AlertCircle, Zap, Globe, BookOpen,
  HelpCircle, FileText, ExternalLink, Sparkles,
} from 'lucide-react';
import { toast } from 'sonner';
import { adminPipelineAutoGenerate, adminPipelineStatus } from '@/utils/api';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

const STEP_LABELS = [
  { icon: BookOpen,   label: 'Chapter Notes',       color: '#8b5cf6' },
  { icon: HelpCircle, label: '20 Topic PYQs',       color: '#f59e0b' },
  { icon: FileText,   label: '30 Flashcards',       color: '#10b981' },
  { icon: Globe,      label: '5 Geo-SEO Blogs',     color: '#3b82f6' },
  { icon: Sparkles,   label: 'PYQ HTML Page',       color: '#ec4899' },
];

export default function PipelineProgressPanel({ adminToken, subjectId, subjectName, onClose, onComplete }) {
  const [status, setStatus]     = useState('idle');
  const [summary, setSummary]   = useState(null);
  const [error, setError]       = useState('');
  const [jobId, setJobId]       = useState(null);
  const [pollData, setPollData] = useState(null);
  const pollRef = useRef(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback((jid) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const res = await adminPipelineStatus(adminToken, jid);
        const data = res.data;
        setPollData(data);
        if (data.status === 'done' || data.status === 'complete') {
          stopPolling();
          setSummary(data.result || data);
          setStatus('done');
          onComplete?.(data.result || data);
          toast.success(`Pipeline complete — ${(data.result || data).total_blogs || 0} blogs published!`);
        } else if (data.status === 'error') {
          stopPolling();
          const detail = data.error || data.message || 'Pipeline failed';
          setError(detail);
          setStatus('error');
          toast.error(`Pipeline error: ${detail}`);
        }
      } catch (e) {
        if (e?.response?.status === 404) {
          stopPolling();
          setError('Job not found or expired');
          setStatus('error');
        }
      }
    }, 3000);
  }, [adminToken, onComplete, stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const runPipeline = useCallback(async () => {
    if (!subjectId) {
      toast.error('No subject selected — pick a subject first');
      return;
    }
    setStatus('running');
    setError('');
    setSummary(null);
    setJobId(null);
    setPollData(null);
    try {
      const res = await adminPipelineAutoGenerate(adminToken, subjectId);
      const data = res.data;

      if (data.job_id) {
        setJobId(data.job_id);
        toast.success('Pipeline started — tracking progress…');
        startPolling(data.job_id);
      } else if (data.status === 'done' || data.total_blogs != null) {
        setSummary(data);
        setStatus('done');
        onComplete?.(data);
        toast.success(`Pipeline complete — ${data.total_blogs || 0} blogs published!`);
      } else {
        setError('Unexpected response from pipeline endpoint');
        setStatus('error');
      }
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || 'Pipeline failed';
      setError(detail);
      setStatus('error');
      toast.error(`Pipeline error: ${detail}`);
    }
  }, [subjectId, adminToken, onComplete, startPolling]);

  const firstBlogUrl = summary?.blog_urls?.[0] || '';

  const pct = pollData
    ? Math.min(99, pollData.progress || 0)
    : 0;

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/75 backdrop-blur-sm" />
      <div
        className="relative flex flex-col rounded-2xl shadow-2xl overflow-hidden"
        style={{
          width: '90vw', maxWidth: '640px', maxHeight: '90vh',
          background: '#0d0d1a', border: '1px solid rgba(139,92,246,0.25)',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: 'rgba(255,255,255,0.07)', background: 'rgba(139,92,246,0.08)' }}>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl flex items-center justify-center"
              style={{ background: 'rgba(139,92,246,0.25)' }}>
              <Zap size={16} className="text-violet-300" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white">Auto-Generate Full Subject</h2>
              <p className="text-xs text-white/40 mt-0.5 truncate max-w-[360px]">
                {subjectName || 'Selected Subject'} — all chapters, MCQs, blogs & PYQ pages
              </p>
            </div>
          </div>
          <button onClick={onClose}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-white/40 hover:text-white/70 hover:bg-white/10 transition-colors">
            <X size={15} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">

          {/* What will be generated */}
          {status === 'idle' && (
            <div className="space-y-3">
              <p className="text-xs text-white/50">
                One click generates a complete content suite for every chapter in
                <span className="font-semibold text-white/70"> {subjectName}</span>:
              </p>
              <div className="grid grid-cols-1 gap-2">
                {STEP_LABELS.map((s, i) => {
                  const Icon = s.icon;
                  return (
                    <div key={i} className="flex items-center gap-3 px-3 py-2.5 rounded-xl"
                      style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
                      <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                        style={{ background: `${s.color}20` }}>
                        <Icon size={13} style={{ color: s.color }} />
                      </div>
                      <span className="text-sm text-white/75">{s.label}</span>
                    </div>
                  );
                })}
              </div>
              <p className="text-xs text-white/30 pt-1">
                Runs as a background job — you can close this panel and check back later.
                Progress updates every few seconds.
              </p>
            </div>
          )}

          {/* Running */}
          {status === 'running' && (
            <div className="flex flex-col items-center gap-5 py-6">
              <div className="relative w-20 h-20">
                <div className="absolute inset-0 rounded-full"
                  style={{ background: 'rgba(139,92,246,0.15)', border: '2px solid rgba(139,92,246,0.30)' }} />
                <div className="absolute inset-0 flex items-center justify-center">
                  <Loader2 size={32} className="text-violet-400 animate-spin" />
                </div>
              </div>
              <div className="text-center">
                <p className="text-sm font-semibold text-white/80">
                  {jobId ? 'Pipeline Running…' : 'Starting Pipeline…'}
                </p>
                {jobId && (
                  <p className="text-[10px] font-mono text-white/25 mt-1">job {jobId.slice(-8)}</p>
                )}
                <p className="text-xs text-white/35 mt-1.5 max-w-sm">
                  Generating chapter notes, MCQs, flashcards, geo-SEO blogs, and PYQ pages for all chapters.
                </p>
              </div>

              {/* Progress bar when polling data available */}
              {pollData && (
                <div className="w-full space-y-2">
                  <div className="flex items-center justify-between text-xs text-white/40">
                    <span>{pollData.message || 'Processing…'}</span>
                    <span>{pct}%</span>
                  </div>
                  <div className="h-2 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
                    <div className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${pct}%`, background: 'linear-gradient(90deg,#7c3aed,#5b21b6)' }} />
                  </div>
                </div>
              )}

              <div className="w-full space-y-2">
                {STEP_LABELS.map((s, i) => {
                  const Icon = s.icon;
                  return (
                    <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-lg"
                      style={{ background: 'rgba(255,255,255,0.025)' }}>
                      <Loader2 size={12} style={{ color: s.color }} className="animate-spin flex-shrink-0" />
                      <span className="text-xs text-white/45">{s.label} — processing…</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Error */}
          {status === 'error' && (
            <div className="flex flex-col items-center gap-4 py-6 text-center">
              <AlertCircle size={40} className="text-red-400" />
              <div>
                <p className="text-sm font-semibold text-red-300">Pipeline Failed</p>
                <p className="text-xs text-white/40 mt-1 max-w-sm">{error}</p>
              </div>
              <button
                onClick={runPipeline}
                className="px-4 py-2 rounded-xl text-sm font-semibold text-white transition"
                style={{ background: '#7c3aed' }}
              >
                Retry Pipeline
              </button>
            </div>
          )}

          {/* Done — Summary */}
          {status === 'done' && summary && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <CheckCircle2 size={18} className="text-emerald-400 flex-shrink-0" />
                <p className="text-sm font-bold text-emerald-300">Pipeline Complete!</p>
              </div>

              {/* Stats grid */}
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {[
                  { label: 'Chapters', value: summary.chapters_processed, color: '#8b5cf6' },
                  { label: 'Topic PYQs', value: summary.total_topic_pyqs,   color: '#f59e0b' },
                  { label: 'Flashcards', value: summary.total_flashcards, color: '#10b981' },
                  { label: 'Blogs',    value: summary.total_blogs,         color: '#3b82f6' },
                ].map((s, i) => (
                  <div key={i} className="rounded-xl p-3 text-center"
                    style={{ background: `${s.color}12`, border: `1px solid ${s.color}25` }}>
                    <p className="text-xl font-bold" style={{ color: s.color }}>{s.value}</p>
                    <p className="text-[10px] text-white/40 mt-0.5">{s.label}</p>
                  </div>
                ))}
              </div>

              {/* PYQ + Sitemap ping */}
              <div className="flex items-center gap-3 flex-wrap">
                <span className="flex items-center gap-1.5 text-xs text-white/50">
                  <Sparkles size={11} className="text-pink-400" />
                  {summary.total_pyq_pages} PYQ pages
                </span>
                <span className="flex items-center gap-1.5 text-xs text-white/50">
                  <Globe size={11} className="text-sky-400" />
                  Sitemap ping: {summary.ping_status || (summary.sitemap_pinged ? 'OK' : 'skipped')}
                </span>
              </div>

              {/* Blog URLs preview */}
              {summary.blog_urls?.length > 0 && (
                <div className="rounded-xl overflow-hidden" style={{ border: '1px solid rgba(255,255,255,0.07)' }}>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-white/30 px-3 py-2"
                    style={{ background: 'rgba(255,255,255,0.025)' }}>
                    Published Blog URLs ({summary.blog_urls.length})
                  </p>
                  <div className="divide-y max-h-[180px] overflow-y-auto"
                    style={{ divideColor: 'rgba(255,255,255,0.05)' }}>
                    {summary.blog_urls.slice(0, 10).map((url, i) => (
                      <div key={i} className="flex items-center justify-between px-3 py-1.5">
                        <span className="text-[11px] text-white/50 truncate">{url}</span>
                        <a
                          href={`${import.meta.env.VITE_FRONTEND_URL || ''}${url}`}
                          target="_blank" rel="noopener noreferrer"
                          className="ml-2 flex-shrink-0 text-violet-400 hover:text-violet-300 transition-colors"
                        >
                          <ExternalLink size={11} />
                        </a>
                      </div>
                    ))}
                    {summary.blog_urls.length > 10 && (
                      <p className="text-[10px] text-white/25 px-3 py-2">
                        +{summary.blog_urls.length - 10} more blogs…
                      </p>
                    )}
                  </div>
                </div>
              )}

              {/* Chapter errors summary */}
              {summary.chapter_results?.some(r => r.errors?.length > 0) && (
                <div className="rounded-xl p-3 text-xs"
                  style={{ background: 'rgba(248,113,113,0.06)', border: '1px solid rgba(248,113,113,0.15)' }}>
                  <p className="text-red-300 font-semibold mb-1">Some errors occurred:</p>
                  {summary.chapter_results
                    .filter(r => r.errors?.length > 0)
                    .map((r, i) => (
                      <div key={i} className="text-white/40">
                        <span className="text-white/60">{r.chapter_title}: </span>
                        {r.errors.join('; ')}
                      </div>
                    ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t"
          style={{ borderColor: 'rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.015)' }}>
          {status === 'idle' && (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 rounded-xl text-sm text-white/50 hover:text-white/70 transition"
              >
                Cancel
              </button>
              <button
                onClick={runPipeline}
                className="flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-bold text-white transition"
                style={{ background: 'linear-gradient(135deg, #7c3aed, #5b21b6)' }}
              >
                <Zap size={14} /> Start Pipeline
              </button>
            </>
          )}
          {status === 'running' && (
            <span className="text-xs text-white/30 italic">
              {jobId ? 'Pipeline running in background — updates every 3 seconds' : 'Starting pipeline…'}
            </span>
          )}
          {(status === 'done' || status === 'error') && (
            <>
              {firstBlogUrl && (
                <a
                  href={`${import.meta.env.VITE_FRONTEND_URL || ''}${firstBlogUrl}`}
                  target="_blank" rel="noopener noreferrer"
                  className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold text-violet-300 transition hover:text-violet-200"
                  style={{ background: 'rgba(139,92,246,0.15)' }}
                >
                  <ExternalLink size={13} /> Open First Blog
                </a>
              )}
              <button
                onClick={onClose}
                className="px-5 py-2 rounded-xl text-sm font-semibold text-white/70 hover:text-white transition"
                style={{ background: 'rgba(255,255,255,0.07)' }}
              >
                Close
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
