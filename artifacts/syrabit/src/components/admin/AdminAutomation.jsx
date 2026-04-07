import { useState, useEffect, useCallback } from 'react';
import {
  Loader2, Zap, AlertTriangle, BookOpen, MessageSquare,
  TrendingUp, RefreshCw, Play, CheckCircle, FileText,
  Search, ArrowRight, Sparkles, Target, Shield, AlertCircle,
  Activity, Lock, XCircle, Info,
} from 'lucide-react';
import axios from 'axios';
import { API_BASE } from '@/utils/api';

function InsightCard({ icon: Icon, title, value, color, children }) {
  return (
    <div className="rounded-2xl p-5" style={{
      background: 'rgba(15,15,30,0.6)',
      border: '1px solid rgba(255,255,255,0.06)',
      backdropFilter: 'blur(12px)',
    }}>
      <div className="flex items-center gap-2 mb-4">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `${color}18` }}>
          <Icon size={16} style={{ color }} />
        </div>
        <div>
          <p className="text-white font-semibold text-sm">{title}</p>
          {value !== undefined && <p className="text-white/25 text-xs">{value}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}

const SEVERITY_STYLE = {
  critical: { bg: 'rgba(239,68,68,0.08)', border: 'rgba(239,68,68,0.25)', text: '#f87171', icon: XCircle },
  high:     { bg: 'rgba(239,68,68,0.06)', border: 'rgba(239,68,68,0.18)', text: '#fca5a5', icon: AlertCircle },
  medium:   { bg: 'rgba(245,158,11,0.07)', border: 'rgba(245,158,11,0.20)', text: '#fcd34d', icon: AlertTriangle },
  warning:  { bg: 'rgba(245,158,11,0.05)', border: 'rgba(245,158,11,0.15)', text: '#fde68a', icon: Info },
  info:     { bg: 'rgba(99,102,241,0.05)', border: 'rgba(99,102,241,0.15)', text: '#a5b4fc', icon: Info },
};

function BlockerItem({ blocker }) {
  const sev = SEVERITY_STYLE[blocker.severity] || SEVERITY_STYLE.warning;
  const Icon = sev.icon;
  return (
    <div className="flex items-start gap-3 px-3 py-2.5 rounded-lg"
      style={{ background: sev.bg, border: `1px solid ${sev.border}` }}>
      <Icon size={13} style={{ color: sev.text, flexShrink: 0, marginTop: 1 }} />
      <div>
        <p className="text-xs font-medium" style={{ color: sev.text }}>
          {blocker.type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
          {blocker.count > 0 && <span className="ml-1 opacity-70">({blocker.count})</span>}
        </p>
        <p className="text-xs text-white/30 mt-0.5 leading-relaxed">{blocker.message}</p>
      </div>
    </div>
  );
}

const STATUS_PILL = {
  ok:       { label: 'Healthy', bg: 'rgba(16,185,129,0.12)', color: '#6ee7b7', border: 'rgba(16,185,129,0.25)' },
  warning:  { label: 'Warning', bg: 'rgba(245,158,11,0.12)', color: '#fcd34d', border: 'rgba(245,158,11,0.25)' },
  degraded: { label: 'Degraded', bg: 'rgba(239,68,68,0.10)', color: '#f87171', border: 'rgba(239,68,68,0.22)' },
  critical: { label: 'Critical', bg: 'rgba(239,68,68,0.14)', color: '#fca5a5', border: 'rgba(239,68,68,0.30)' },
  error:    { label: 'Error', bg: 'rgba(239,68,68,0.14)', color: '#fca5a5', border: 'rgba(239,68,68,0.30)' },
};

export default function AdminAutomation({ adminToken }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState(null);
  const [scraperStatus, setScraperStatus] = useState(null);
  const [scraperLoading, setScraperLoading] = useState(true);

  const headers = { withCredentials: true };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/admin/automation/insights`, headers);
      setData(res.data);
    } catch {}
    finally { setLoading(false); }
  }, []);

  const loadScraperStatus = useCallback(async () => {
    setScraperLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/admin/cms/scraper-status`, headers);
      setScraperStatus(res.data);
    } catch (e) {
      setScraperStatus({ status: 'error', blockers: [{ type: 'fetch_error', message: e?.message || 'Failed to fetch scraper status', severity: 'high' }], stats: {} });
    } finally {
      setScraperLoading(false);
    }
  }, []);

  useEffect(() => { load(); loadScraperStatus(); }, [load, loadScraperStatus]);

  const handleAutoGenerate = async () => {
    setGenerating(true);
    try {
      const res = await axios.post(`${API_BASE}/admin/automation/auto-generate`, {}, headers);
      setGenerated(res.data);
      load();
    } catch {}
    finally { setGenerating(false); }
  };

  if (loading) return (
    <div className="flex justify-center p-10">
      <Loader2 size={24} className="animate-spin text-violet-400/60" />
    </div>
  );

  const gaps = data?.content_gaps || [];
  const lowContent = data?.low_content_subjects || [];
  const scraperSt = scraperStatus?.status || 'ok';
  const scraperPill = STATUS_PILL[scraperSt] || STATUS_PILL.ok;
  const scraperStats = scraperStatus?.stats || {};
  const scraperBlockers = scraperStatus?.blockers || [];
  const recentPlans = scraperStatus?.recent_plans || [];

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-white/90 font-bold text-lg flex items-center gap-2">
            <Zap size={18} className="text-amber-400" />
            Automation Engine
          </h2>
          <p className="text-white/30 text-sm mt-1">AI-powered content insights, gap detection, and auto-generation</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleAutoGenerate}
            disabled={generating || gaps.length === 0}
            className="flex items-center gap-2 disabled:opacity-50 text-white rounded-xl px-4 py-2 text-sm font-medium transition-all hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #7c3aed, #6d28d9)', boxShadow: '0 2px 12px rgba(124,58,237,0.3)' }}
          >
            {generating ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Auto-Generate Topics
          </button>
          <button
            onClick={() => { load(); loadScraperStatus(); }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs text-white/30 hover:text-white transition-colors"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}
          >
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {generated && (
        <div className="rounded-2xl p-4" style={{ background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.2)' }}>
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle size={14} className="text-emerald-400" />
            <span className="text-emerald-300 text-sm font-medium">Generated {generated.count} new topics as drafts</span>
          </div>
          <div className="space-y-1">
            {generated.generated?.map((g, i) => (
              <p key={i} className="text-white/30 text-xs">• {g.title} <code className="text-white/20">/{g.slug}</code></p>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { value: data?.total_seo_topics || 0, label: 'Total SEO Topics', color: '#a78bfa' },
          { value: data?.published_count || 0, label: 'Published Pages', color: '#6ee7b7' },
          { value: gaps.length, label: 'Content Gaps', color: '#fbbf24' },
          { value: data?.promotable_chats || 0, label: 'Promotable Chats', color: '#60a5fa' },
        ].map((s, i) => (
          <div key={i} className="rounded-2xl p-4 text-center" style={{
            background: 'rgba(15,15,30,0.6)',
            border: '1px solid rgba(255,255,255,0.06)',
            backdropFilter: 'blur(12px)',
          }}>
            <p className="text-2xl font-bold" style={{ color: s.color }}>{s.value}</p>
            <p className="text-white/25 text-xs mt-1">{s.label}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <InsightCard
          icon={Search}
          title="Content Gaps"
          value={`${gaps.length} topics students asked about but have no SEO page`}
          color="#f59e0b"
        >
          {gaps.length === 0 ? (
            <p className="text-white/20 text-sm text-center py-4">No content gaps detected</p>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {gaps.map((gap, i) => (
                <div key={i} className="flex items-center gap-2 p-2 rounded-lg" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                  <AlertTriangle size={12} className="text-amber-400 flex-shrink-0" />
                  <span className="text-white/50 text-xs flex-1 truncate">{gap.query}</span>
                  <span className="text-white/25 text-xs flex-shrink-0">{gap.count}×</span>
                </div>
              ))}
            </div>
          )}
        </InsightCard>

        <InsightCard
          icon={BookOpen}
          title="Low-Content Subjects"
          value={`${lowContent.length} subjects with fewer than 3 SEO pages`}
          color="#ef4444"
        >
          {lowContent.length === 0 ? (
            <p className="text-white/20 text-sm text-center py-4">All subjects have adequate content</p>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {lowContent.map((subj, i) => (
                <div key={i} className="flex items-center gap-2 p-2 rounded-lg" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                  <BookOpen size={12} className="text-red-400 flex-shrink-0" />
                  <span className="text-white/50 text-xs flex-1 truncate">{subj.name}</span>
                  <span className="text-white/25 text-xs flex-shrink-0">{subj.seo_pages} pages</span>
                </div>
              ))}
            </div>
          )}
        </InsightCard>
      </div>

      <div className="rounded-2xl p-5" style={{
        background: 'rgba(15,15,30,0.6)',
        border: '1px solid rgba(255,255,255,0.06)',
        backdropFilter: 'blur(12px)',
      }}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Shield size={16} className="text-violet-400" />
            <h3 className="text-white font-semibold text-sm">Personalized CMS Scraper</h3>
          </div>
          {scraperLoading ? (
            <Loader2 size={13} className="animate-spin text-white/25" />
          ) : (
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold" style={{ background: scraperPill.bg, color: scraperPill.color, border: `1px solid ${scraperPill.border}` }}>
              {scraperPill.label}
            </span>
          )}
        </div>

        {scraperLoading ? (
          <div className="flex justify-center py-4">
            <Loader2 size={20} className="animate-spin text-white/20" />
          </div>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2 mb-2">
              {[
                { label: 'Total Plans', value: scraperStats.total_plans ?? '—', color: '#a78bfa' },
                { label: 'Published', value: scraperStats.published_plans ?? '—', color: '#6ee7b7' },
                { label: 'Errors', value: scraperStats.error_plans ?? '—', color: scraperStats.error_plans > 0 ? '#f87171' : '#64748b' },
              ].map((s, i) => (
                <div key={i} className="rounded-lg p-2.5 text-center" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <p className="text-base font-bold" style={{ color: s.color }}>{s.value}</p>
                  <p className="text-[10px] text-white/25 mt-0.5">{s.label}</p>
                </div>
              ))}
            </div>
            {(scraperStats.paid_users !== undefined || scraperStats.free_users !== undefined) && (
              <div className="grid grid-cols-2 gap-2 mb-4">
                <div className="rounded-lg p-2 text-center" style={{ background: 'rgba(16,185,129,0.04)', border: '1px solid rgba(16,185,129,0.12)' }}>
                  <p className="text-sm font-bold text-emerald-400">{scraperStats.paid_users ?? '—'}</p>
                  <p className="text-[10px] text-white/25">Paid Users (can access)</p>
                </div>
                <div className="rounded-lg p-2 text-center" style={{ background: 'rgba(148,163,184,0.04)', border: '1px solid rgba(148,163,184,0.10)' }}>
                  <p className="text-sm font-bold text-white/40">{scraperStats.free_users ?? '—'}</p>
                  <p className="text-[10px] text-white/25">Free Users (402 gated)</p>
                </div>
              </div>
            )}

            {scraperBlockers.length === 0 ? (
              <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg" style={{ background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.15)' }}>
                <CheckCircle size={13} className="text-emerald-400 flex-shrink-0" />
                <span className="text-xs text-emerald-300">No scraper blockers detected — CMS pipeline is healthy</span>
              </div>
            ) : (
              <div className="space-y-2">
                <p className="text-xs text-white/25 font-medium uppercase tracking-wide mb-1">Detected Blockers</p>
                {scraperBlockers.map((b, i) => <BlockerItem key={i} blocker={b} />)}
              </div>
            )}

            {recentPlans.length > 0 && (
              <div className="mt-4">
                <p className="text-[10px] text-white/25 font-semibold uppercase tracking-widest mb-2">Recent Plans</p>
                <div className="space-y-1.5 max-h-36 overflow-y-auto">
                  {recentPlans.map((p, i) => (
                    <div key={i} className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg" style={{ background: 'rgba(255,255,255,0.02)' }}>
                      <FileText size={11} className="text-white/25 flex-shrink-0" />
                      <span className="text-xs text-white/50 flex-1 truncate">{p.title || p.id}</span>
                      <span className="text-[10px] text-white/20 flex-shrink-0">{p.word_count}w</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <div className="rounded-2xl p-5" style={{
        background: 'rgba(15,15,30,0.6)',
        border: '1px solid rgba(255,255,255,0.06)',
        backdropFilter: 'blur(12px)',
      }}>
        <div className="flex items-center gap-2 mb-4">
          <Target size={16} className="text-violet-400" />
          <h3 className="text-white font-semibold text-sm">Automation Rules</h3>
        </div>
        <div className="space-y-3">
          {[
            { label: 'Auto-detect content gaps from chat logs', status: 'active', icon: Search },
            { label: 'Identify low-content subjects for generation', status: 'active', icon: BookOpen },
            { label: 'Flag high-quality chats for QA promotion', status: 'active', icon: MessageSquare },
            { label: 'Auto-generate SEO topics from gaps', status: 'manual', icon: Sparkles },
            { label: 'Personalized CMS scraper blocker detection', status: 'active', icon: Shield },
          ].map((rule, i) => (
            <div key={i} className="flex items-center gap-3 p-3 rounded-lg" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
              <rule.icon size={14} className="text-white/30" />
              <span className="text-white/50 text-sm flex-1">{rule.label}</span>
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                rule.status === 'active'
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                  : 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
              }`}>
                {rule.status === 'active' ? 'Active' : 'Manual'}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
