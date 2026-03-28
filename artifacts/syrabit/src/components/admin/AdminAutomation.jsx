import { useState, useEffect, useCallback } from 'react';
import {
  Loader2, Zap, AlertTriangle, BookOpen, MessageSquare,
  TrendingUp, RefreshCw, Play, CheckCircle, FileText,
  Search, ArrowRight, Sparkles, Target,
} from 'lucide-react';
import axios from 'axios';
import { API_BASE } from '@/utils/api';

function InsightCard({ icon: Icon, title, value, color, children }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `${color}18` }}>
          <Icon size={16} style={{ color }} />
        </div>
        <div>
          <p className="text-white font-semibold text-sm">{title}</p>
          {value !== undefined && <p className="text-slate-500 text-xs">{value}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}

export default function AdminAutomation({ adminToken }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState(null);

  const headers = { withCredentials: true };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/admin/automation/insights`, headers);
      setData(res.data);
    } catch {}
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

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
      <Loader2 size={24} className="animate-spin text-slate-400" />
    </div>
  );

  const gaps = data?.content_gaps || [];
  const lowContent = data?.low_content_subjects || [];

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-white font-bold text-lg flex items-center gap-2">
            <Zap size={18} className="text-amber-400" />
            Automation Engine
          </h2>
          <p className="text-slate-500 text-sm mt-1">AI-powered content insights, gap detection, and auto-generation</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleAutoGenerate}
            disabled={generating || gaps.length === 0}
            className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
          >
            {generating ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Auto-Generate Topics
          </button>
          <button
            onClick={load}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs text-slate-400 hover:text-white bg-slate-800 border border-slate-700"
          >
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {generated && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle size={14} className="text-emerald-400" />
            <span className="text-emerald-300 text-sm font-medium">Generated {generated.count} new topics as drafts</span>
          </div>
          <div className="space-y-1">
            {generated.generated?.map((g, i) => (
              <p key={i} className="text-slate-400 text-xs">• {g.title} <code className="text-slate-600">/{g.slug}</code></p>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 text-center">
          <p className="text-2xl font-bold text-violet-400">{data?.total_seo_topics || 0}</p>
          <p className="text-slate-500 text-xs mt-1">Total SEO Topics</p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 text-center">
          <p className="text-2xl font-bold text-emerald-400">{data?.published_count || 0}</p>
          <p className="text-slate-500 text-xs mt-1">Published Pages</p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 text-center">
          <p className="text-2xl font-bold text-amber-400">{gaps.length}</p>
          <p className="text-slate-500 text-xs mt-1">Content Gaps</p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 text-center">
          <p className="text-2xl font-bold text-blue-400">{data?.promotable_chats || 0}</p>
          <p className="text-slate-500 text-xs mt-1">Promotable Chats</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <InsightCard
          icon={Search}
          title="Content Gaps"
          value={`${gaps.length} topics students asked about but have no SEO page`}
          color="#f59e0b"
        >
          {gaps.length === 0 ? (
            <p className="text-slate-600 text-sm text-center py-4">No content gaps detected</p>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {gaps.map((gap, i) => (
                <div key={i} className="flex items-center gap-2 p-2 bg-slate-800/50 rounded-lg">
                  <AlertTriangle size={12} className="text-amber-400 flex-shrink-0" />
                  <span className="text-slate-300 text-xs flex-1 truncate">{gap.query}</span>
                  <span className="text-slate-500 text-xs flex-shrink-0">{gap.count}×</span>
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
            <p className="text-slate-600 text-sm text-center py-4">All subjects have adequate content</p>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {lowContent.map((subj, i) => (
                <div key={i} className="flex items-center gap-2 p-2 bg-slate-800/50 rounded-lg">
                  <BookOpen size={12} className="text-red-400 flex-shrink-0" />
                  <span className="text-slate-300 text-xs flex-1 truncate">{subj.name}</span>
                  <span className="text-slate-500 text-xs flex-shrink-0">{subj.seo_pages} pages</span>
                </div>
              ))}
            </div>
          )}
        </InsightCard>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
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
          ].map((rule, i) => (
            <div key={i} className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-lg">
              <rule.icon size={14} className="text-slate-400" />
              <span className="text-slate-300 text-sm flex-1">{rule.label}</span>
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
