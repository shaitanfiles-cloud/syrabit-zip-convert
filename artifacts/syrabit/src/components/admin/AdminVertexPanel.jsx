/**
 * AdminVertexPanel — Vertex AI / Gemini AI Services Hub
 * 9 integrated AI capabilities powered by GEMINI_API_KEY
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Cpu, Search, Languages, Zap, BarChart2, Lightbulb, FileSearch,
  AlertTriangle, CheckCircle, Loader2, Copy, ChevronDown, ChevronUp,
  BookOpen, Star, TrendingUp, FileUp, RefreshCw, Sparkles,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  vertexHealth, vertexSemanticSearch, vertexTranslate,
  vertexQualityScore, vertexSuggestTopics, vertexSeoMeta, vertexContentGaps,
  getAllSubjects, getClasses, API_BASE,
} from '@/utils/api';
import axios from 'axios';
import { adminSeoExtractTopics, adminSeoCreateTopic } from '@/utils/api';

// ── Hub context reader ────────────────────────────────────────────────────────
function readHubCtx() {
  try {
    const raw = localStorage.getItem('syrabit_hub_ctx');
    if (!raw) return null;
    const ctx = JSON.parse(raw);
    if (Date.now() - (ctx._ts || 0) > 2 * 60 * 60 * 1000) return null;
    return ctx;
  } catch { return null; }
}

const card = {
  background: 'rgba(255,255,255,0.03)',
  border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 16,
  padding: 20,
};

const btn = (color = '#8b5cf6') => ({
  background: `linear-gradient(135deg, ${color}22, ${color}11)`,
  border: `1px solid ${color}44`,
  color,
  borderRadius: 10,
  padding: '8px 16px',
  fontSize: 13,
  fontWeight: 600,
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  transition: 'all 0.15s',
});

function Badge({ label, color = '#8b5cf6' }) {
  return (
    <span style={{ background: `${color}22`, color, border: `1px solid ${color}44`, borderRadius: 20, padding: '2px 10px', fontSize: 11, fontWeight: 700 }}>
      {label}
    </span>
  );
}

function ScoreBar({ label, value }) {
  const pct = Math.round((value / 10) * 100);
  const color = value >= 8 ? '#10b981' : value >= 6 ? '#f59e0b' : '#ef4444';
  return (
    <div className="flex items-center gap-3 mb-1">
      <span style={{ width: 130, fontSize: 12, color: 'rgba(232,232,232,0.6)' }}>{label}</span>
      <div style={{ flex: 1, height: 6, background: 'rgba(255,255,255,0.07)', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.4s' }} />
      </div>
      <span style={{ width: 24, fontSize: 12, fontWeight: 700, color }}>{value}</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SERVICE CARDS
// ─────────────────────────────────────────────────────────────────────────────

function SemanticSearchCard({ token }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);

  async function run() {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const r = await vertexSemanticSearch(token, query.trim(), 10);
      setResults(r.data.results || []);
    } catch {
      toast.error('Semantic search failed');
    } finally { setLoading(false); }
  }

  return (
    <div style={card}>
      <div className="flex items-center gap-2 mb-4">
        <Search size={16} color="#3b82f6" />
        <span style={{ fontWeight: 700, color: '#e8e8e8' }}>Semantic Topic Search</span>
        <Badge label="Embeddings" color="#3b82f6" />
      </div>
      <p style={{ fontSize: 12, color: 'rgba(232,232,232,0.5)', marginBottom: 12 }}>
        Find topics by meaning, not keyword. Powered by text-embedding-004.
      </p>
      <div className="flex gap-2 mb-4">
        <input
          value={query} onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && run()}
          placeholder="e.g. chemical bonding in organic chemistry"
          style={{ flex: 1, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: '8px 14px', color: '#e8e8e8', fontSize: 13 }}
        />
        <button onClick={run} disabled={loading} style={btn('#3b82f6')}>
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
          Search
        </button>
      </div>
      {results.length > 0 && (
        <div style={{ maxHeight: 260, overflowY: 'auto' }}>
          {results.map((r, i) => (
            <div key={i} className="flex items-center gap-3 py-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: '#3b82f6', width: 24 }}>#{i + 1}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: '#e8e8e8', fontWeight: 600 }}>{r.title}</div>
                <div style={{ fontSize: 11, color: 'rgba(232,232,232,0.45)' }}>{r.subject_name} · {r.class_name}</div>
              </div>
              <span style={{ background: 'rgba(59,130,246,0.15)', color: '#3b82f6', borderRadius: 8, padding: '2px 8px', fontSize: 11, fontWeight: 700 }}>
                {(r.score * 100).toFixed(0)}%
              </span>
              <Badge label={r.status || 'draft'} color={r.status === 'published' ? '#10b981' : '#64748b'} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const FALLBACK_LANGS = [
  { code: 'as', label: 'Assamese (অসমীয়া)' },
  { code: 'hi', label: 'Hindi (हिन्दी)' },
  { code: 'bn', label: 'Bengali (বাংলা)' },
  { code: 'bho', label: 'Bodo (बड़ो)' },
];

function TranslationCard({ token }) {
  const [text, setText] = useState('');
  const [lang, setLang] = useState('as');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const [langs, setLangs] = useState(FALLBACK_LANGS);

  useEffect(() => {
    axios.get(`${API_BASE}/admin/translation/languages`, { withCredentials: true })
      .then(r => {
        const list = (r.data || []).filter(l => l.code && l.label);
        if (list.length > 0) setLangs(list);
      })
      .catch(() => {});
  }, []);

  async function run() {
    if (!text.trim()) return;
    setLoading(true);
    try {
      const r = await vertexTranslate(token, text.trim(), lang);
      setResult(r.data.translated || '');
      toast.success('Translation complete');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Translation failed');
    } finally { setLoading(false); }
  }

  return (
    <div style={card}>
      <div className="flex items-center gap-2 mb-4">
        <Languages size={16} color="#10b981" />
        <span style={{ fontWeight: 700, color: '#e8e8e8' }}>Regional Language Translation</span>
        <Badge label="Gemini Multilingual" color="#10b981" />
      </div>
      <p style={{ fontSize: 12, color: 'rgba(232,232,232,0.5)', marginBottom: 12 }}>
        Translate educational content into Assamese, Hindi, Bengali, or Bodo. Keeps all technical terms intact.
      </p>
      <div className="flex gap-2 mb-3">
        <select value={lang} onChange={e => setLang(e.target.value)}
          style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: '8px 12px', color: '#e8e8e8', fontSize: 13 }}>
          {langs.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}
        </select>
        <button onClick={run} disabled={loading || !text.trim()} style={btn('#10b981')}>
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Languages size={13} />}
          Translate
        </button>
      </div>
      <textarea value={text} onChange={e => setText(e.target.value)} rows={4}
        placeholder="Paste English content here to translate..."
        style={{ width: '100%', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: '10px 14px', color: '#e8e8e8', fontSize: 13, resize: 'vertical', fontFamily: 'inherit' }}
      />
      {result && (
        <div style={{ marginTop: 12, background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.2)', borderRadius: 10, padding: 14 }}>
          <div className="flex items-center justify-between mb-2">
            <span style={{ fontSize: 11, fontWeight: 700, color: '#10b981', textTransform: 'uppercase' }}>Translation</span>
            <button onClick={() => { navigator.clipboard.writeText(result); toast.success('Copied!'); }}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#10b981' }}>
              <Copy size={13} />
            </button>
          </div>
          <p style={{ fontSize: 14, color: '#e8e8e8', lineHeight: 1.7 }}>{result}</p>
        </div>
      )}
    </div>
  );
}

function QualityScoreCard({ token }) {
  const [content, setContent] = useState('');
  const [pageType, setPageType] = useState('notes');
  const [topic, setTopic] = useState('');
  const [subject, setSubject] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    if (!content.trim()) return;
    setLoading(true);
    try {
      const r = await vertexQualityScore(token, content.trim(), pageType, topic, subject);
      setResult(r.data);
    } catch {
      toast.error('Quality scoring failed');
    } finally { setLoading(false); }
  }

  return (
    <div style={card}>
      <div className="flex items-center gap-2 mb-4">
        <BarChart2 size={16} color="#f59e0b" />
        <span style={{ fontWeight: 700, color: '#e8e8e8' }}>Content Quality Scorer</span>
        <Badge label="Gemini Review" color="#f59e0b" />
      </div>
      <p style={{ fontSize: 12, color: 'rgba(232,232,232,0.5)', marginBottom: 12 }}>
        Score accuracy, completeness, clarity and exam relevance before publishing.
      </p>
      <div className="flex gap-2 mb-3">
        <input value={topic} onChange={e => setTopic(e.target.value)} placeholder="Topic"
          style={{ flex: 1, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: '7px 12px', color: '#e8e8e8', fontSize: 13 }} />
        <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="Subject"
          style={{ flex: 1, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: '7px 12px', color: '#e8e8e8', fontSize: 13 }} />
        <select value={pageType} onChange={e => setPageType(e.target.value)}
          style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: '7px 12px', color: '#e8e8e8', fontSize: 13 }}>
          {['notes', 'mcqs', 'definition', 'important-questions', 'examples'].map(t =>
            <option key={t} value={t}>{t}</option>
          )}
        </select>
      </div>
      <textarea value={content} onChange={e => setContent(e.target.value)} rows={4}
        placeholder="Paste content to score..."
        style={{ width: '100%', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: '10px 14px', color: '#e8e8e8', fontSize: 13, resize: 'vertical', fontFamily: 'inherit', marginBottom: 10 }}
      />
      <button onClick={run} disabled={loading || !content.trim()} style={btn('#f59e0b')}>
        {loading ? <Loader2 size={13} className="animate-spin" /> : <BarChart2 size={13} />}
        Score Content
      </button>
      {result && (
        <div style={{ marginTop: 14, background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.2)', borderRadius: 10, padding: 16 }}>
          <div className="flex items-center gap-3 mb-4">
            <div style={{ fontSize: 32, fontWeight: 900, color: result.overall >= 7 ? '#10b981' : result.overall >= 5 ? '#f59e0b' : '#ef4444' }}>
              {result.overall}/10
            </div>
            <div>
              <div style={{ fontSize: 12, color: 'rgba(232,232,232,0.5)', fontWeight: 600 }}>Overall Score</div>
              <div style={{ fontSize: 11, color: result.overall >= 7 ? '#10b981' : '#f59e0b' }}>
                {result.overall >= 8 ? 'Ready to publish' : result.overall >= 6 ? 'Needs minor edits' : 'Needs improvement'}
              </div>
            </div>
          </div>
          <ScoreBar label="Accuracy" value={result.accuracy || 0} />
          <ScoreBar label="Completeness" value={result.completeness || 0} />
          <ScoreBar label="Clarity" value={result.clarity || 0} />
          <ScoreBar label="Exam Relevance" value={result.exam_relevance || 0} />
          {result.issues?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#ef4444', marginBottom: 4 }}>ISSUES</div>
              {result.issues.map((iss, i) => <div key={i} style={{ fontSize: 12, color: 'rgba(232,232,232,0.6)', paddingLeft: 10 }}>• {iss}</div>)}
            </div>
          )}
          {result.strengths?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#10b981', marginBottom: 4 }}>STRENGTHS</div>
              {result.strengths.map((s, i) => <div key={i} style={{ fontSize: 12, color: 'rgba(232,232,232,0.6)', paddingLeft: 10 }}>✓ {s}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const FALLBACK_SUBJECTS = ['Physics', 'Chemistry', 'Mathematics', 'Biology', 'English', 'Accountancy', 'Business Studies', 'Economics', 'History', 'Political Science', 'Geography'];
const FALLBACK_CLASSES = ['Class 11', 'Class 12', 'Degree 1st Year', 'Degree 2nd Year', 'Degree 3rd Year'];

function TopicSuggesterCard({ token, onNavigate }) {
  const [subjects, setSubjects] = useState(FALLBACK_SUBJECTS);
  const [classes, setClasses] = useState(FALLBACK_CLASSES);
  const [subject, setSubject] = useState('Physics');
  const [classN, setClassN] = useState('Class 11');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [optionsError, setOptionsError] = useState(false);
  const [pushing, setPushing] = useState(false);

  const hubCtx = readHubCtx();

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      getAllSubjects(),
      getClasses(),
    ]).then(([subRes, clsRes]) => {
      if (cancelled) return;
      if (subRes.status === 'fulfilled') {
        const list = (subRes.value.data || []).map(s => s.name || s.title || s).filter(Boolean);
        if (list.length > 0) {
          setSubjects(list);
          // Pre-fill from hub context if available
          const hubSub = hubCtx?.subjectName;
          setSubject(hubSub && list.includes(hubSub) ? hubSub : list[0]);
        }
      } else {
        setOptionsError(true);
      }
      if (clsRes.status === 'fulfilled') {
        const list = (clsRes.value.data || []).map(c => c.name || c.title || c).filter(Boolean);
        if (list.length > 0) {
          setClasses(list);
          const hubCls = hubCtx?.className;
          setClassN(hubCls && list.includes(hubCls) ? hubCls : list[0]);
        }
      }
    });
    return () => { cancelled = true; };
  }, []);

  async function run() {
    setLoading(true);
    try {
      const r = await vertexSuggestTopics(token, subject, classN);
      setResults(r.data.suggestions || []);
      toast.success(`${r.data.suggestions?.length || 0} topic suggestions ready`);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Topic suggestion failed');
    } finally { setLoading(false); }
  }

  return (
    <div style={card}>
      <div className="flex items-center gap-2 mb-4">
        <Lightbulb size={16} color="#a855f7" />
        <span style={{ fontWeight: 700, color: '#e8e8e8' }}>Topic Suggester</span>
        <Badge label="Gap Analysis" color="#a855f7" />
      </div>
      <p style={{ fontSize: 12, color: 'rgba(232,232,232,0.5)', marginBottom: optionsError ? 8 : 12 }}>
        AI finds high-search-volume topics you haven't covered yet. Add them to your SEO pipeline.
      </p>
      {optionsError && (
        <p style={{ fontSize: 11, color: '#f59e0b', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)', borderRadius: 6, padding: '4px 10px', marginBottom: 10 }}>
          Could not load subjects from API — using defaults. Check backend connection.
        </p>
      )}
      <div className="flex gap-2 mb-4">
        <select value={subject} onChange={e => setSubject(e.target.value)}
          style={{ flex: 1, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: '8px 12px', color: '#e8e8e8', fontSize: 13 }}>
          {subjects.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={classN} onChange={e => setClassN(e.target.value)}
          style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: '8px 12px', color: '#e8e8e8', fontSize: 13 }}>
          {classes.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <button onClick={run} disabled={loading} style={btn('#a855f7')}>
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Lightbulb size={13} />}
          Suggest
        </button>
      </div>
      {results.length > 0 && (
        <div>
          <div style={{ maxHeight: 300, overflowY: 'auto' }}>
            {results.map((r, i) => (
              <div key={i} style={{ padding: '10px 14px', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                <div style={{ marginTop: 2 }}>
                  <Badge label={r.priority || 'medium'} color={r.priority === 'high' ? '#ef4444' : '#f59e0b'} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#e8e8e8' }}>{r.title}</div>
                  <div style={{ fontSize: 11, color: 'rgba(232,232,232,0.45)', marginTop: 2 }}>{r.reason}</div>
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#a855f7' }}>~{r.search_volume_estimate?.toLocaleString()}</div>
                  <div style={{ fontSize: 10, color: 'rgba(232,232,232,0.35)' }}>searches/mo</div>
                </div>
              </div>
            ))}
          </div>
          {onNavigate && (
            <div style={{ display: 'flex', gap: 8, marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <button
                onClick={async () => {
                  if (!token) { toast.error('Not authenticated'); return; }
                  setPushing(true);
                  toast.loading('Pushing topics to SEO pipeline…', { id: 'push-seo' });
                  try {
                    let pushed = 0;
                    for (const r of results) {
                      await adminSeoCreateTopic(token, {
                        title:      r.title,
                        slug:       r.title.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
                        subject_id: hubCtx?.subjectId || '',
                        chapter_id: '',
                        definition: r.reason || '',
                        status:     'published',
                      });
                      pushed++;
                    }
                    toast.success(`Pushed ${pushed} topics to SEO pipeline`, { id: 'push-seo' });
                    onNavigate('seomanager');
                  } catch (e) {
                    toast.error(e.response?.data?.detail || 'Push failed', { id: 'push-seo' });
                  } finally { setPushing(false); }
                }}
                disabled={pushing}
                style={{ ...btn('#a855f7'), fontSize: 12 }}>
                {pushing ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
                Push {results.length} topics to SEO
              </button>
              <button
                onClick={() => onNavigate('seomanager')}
                style={{ background: 'rgba(168,85,247,0.10)', border: '1px solid rgba(168,85,247,0.25)', color: '#d8b4fe', borderRadius: 8, padding: '7px 14px', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
                Go to SEO Manager →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SeoMetaCard({ token, onNavigate }) {
  const hubCtx = readHubCtx();
  const [form, setForm] = useState({
    topic:           '',
    subject:         '',
    class_name:      'Class 11',
    page_type:       'notes',
    board:           'AHSEC',
    content_preview: '',
  });

  // Pre-fill from hub context on mount
  useEffect(() => {
    const ctx = readHubCtx();
    if (!ctx) return;
    setForm(f => ({
      ...f,
      subject:    ctx.subjectName || f.subject,
      class_name: ctx.className   || f.class_name,
    }));
  }, []);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    if (!form.topic) return;
    setLoading(true);
    try {
      const r = await vertexSeoMeta(token, form);
      setResult(r.data);
      toast.success('SEO metadata generated');
    } catch {
      toast.error('SEO meta generation failed');
    } finally { setLoading(false); }
  }

  const inp = { background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: '7px 12px', color: '#e8e8e8', fontSize: 13 };

  return (
    <div style={card}>
      <div className="flex items-center gap-2 mb-4">
        <TrendingUp size={16} color="#06b6d4" />
        <span style={{ fontWeight: 700, color: '#e8e8e8' }}>SEO Meta Generator</span>
        <Badge label="Structured Output" color="#06b6d4" />
      </div>
      <p style={{ fontSize: 12, color: 'rgba(232,232,232,0.5)', marginBottom: 12 }}>
        Generate title (60 chars), meta description (160 chars), keywords, OG tags — all optimised for AssamBoard search intent.
      </p>
      <div className="grid grid-cols-2 gap-2 mb-2">
        <input value={form.topic} onChange={e => setForm(f => ({ ...f, topic: e.target.value }))} placeholder="Topic *" style={inp} />
        <input value={form.subject} onChange={e => setForm(f => ({ ...f, subject: e.target.value }))} placeholder="Subject" style={inp} />
        <select value={form.class_name} onChange={e => setForm(f => ({ ...f, class_name: e.target.value }))} style={inp}>
          {['Class 11', 'Class 12', 'Degree 1st Year'].map(c => <option key={c}>{c}</option>)}
        </select>
        <select value={form.page_type} onChange={e => setForm(f => ({ ...f, page_type: e.target.value }))} style={inp}>
          {['notes', 'mcqs', 'definition', 'important-questions', 'examples', 'syllabus'].map(t => <option key={t}>{t}</option>)}
        </select>
      </div>
      <textarea value={form.content_preview} onChange={e => setForm(f => ({ ...f, content_preview: e.target.value }))} rows={2}
        placeholder="Optional: paste first 200 chars of content for better meta..."
        style={{ ...inp, width: '100%', resize: 'none', marginBottom: 10, fontFamily: 'inherit' }}
      />
      <button onClick={run} disabled={loading || !form.topic} style={btn('#06b6d4')}>
        {loading ? <Loader2 size={13} className="animate-spin" /> : <TrendingUp size={13} />}
        Generate Meta
      </button>
      {result && (
        <div style={{ marginTop: 14, background: 'rgba(6,182,212,0.05)', border: '1px solid rgba(6,182,212,0.2)', borderRadius: 10, padding: 16 }}>
          {[['title', 'Title', '#06b6d4'], ['meta_description', 'Meta Description', '#10b981'], ['og_title', 'OG Title', '#a855f7'], ['og_description', 'OG Description', '#f59e0b']].map(([key, label, color]) => (
            result[key] && (
              <div key={key} style={{ marginBottom: 10 }}>
                <div className="flex items-center justify-between mb-1">
                  <span style={{ fontSize: 10, fontWeight: 700, color, textTransform: 'uppercase' }}>{label}</span>
                  <span style={{ fontSize: 10, color: 'rgba(232,232,232,0.35)' }}>{result[key].length} chars</span>
                </div>
                <div style={{ fontSize: 13, color: '#e8e8e8', background: 'rgba(255,255,255,0.04)', borderRadius: 8, padding: '8px 10px' }}>
                  {result[key]}
                </div>
              </div>
            )
          ))}
          {result.keywords?.length > 0 && (
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#8b5cf6', textTransform: 'uppercase', marginBottom: 6 }}>Keywords</div>
              <div className="flex flex-wrap gap-1">
                {result.keywords.map((kw, i) => (
                  <span key={i} style={{ background: 'rgba(139,92,246,0.12)', border: '1px solid rgba(139,92,246,0.25)', color: '#a78bfa', borderRadius: 20, padding: '2px 8px', fontSize: 11 }}>{kw}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ContentGapsCard({ token }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    setLoading(true);
    try {
      const r = await vertexContentGaps(token);
      setData(r.data);
    } catch {
      toast.error('Content gap analysis failed');
    } finally { setLoading(false); }
  }

  const priorityColor = (p) => p === 'high' ? '#ef4444' : p === 'medium' ? '#f59e0b' : '#64748b';

  return (
    <div style={card}>
      <div className="flex items-center gap-2 mb-4">
        <FileSearch size={16} color="#ef4444" />
        <span style={{ fontWeight: 700, color: '#e8e8e8' }}>Content Gap Finder</span>
        <Badge label="Search vs Published" color="#ef4444" />
      </div>
      <p style={{ fontSize: 12, color: 'rgba(232,232,232,0.5)', marginBottom: 12 }}>
        Cross-references your published pages with actual student search queries to find high-value missing content.
      </p>
      <button onClick={run} disabled={loading} style={btn('#ef4444')}>
        {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
        Analyse Gaps
      </button>
      {data && (
        <div style={{ marginTop: 14 }}>
          <div className="flex gap-4 mb-4">
            <div style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 10, padding: '8px 16px', textAlign: 'center' }}>
              <div style={{ fontSize: 22, fontWeight: 900, color: '#ef4444' }}>{data.gaps?.length || 0}</div>
              <div style={{ fontSize: 10, color: 'rgba(232,232,232,0.45)' }}>Gaps Found</div>
            </div>
            <div style={{ background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)', borderRadius: 10, padding: '8px 16px', textAlign: 'center' }}>
              <div style={{ fontSize: 22, fontWeight: 900, color: '#10b981' }}>{data.published_count}</div>
              <div style={{ fontSize: 10, color: 'rgba(232,232,232,0.45)' }}>Published Pages</div>
            </div>
            <div style={{ background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.2)', borderRadius: 10, padding: '8px 16px', textAlign: 'center' }}>
              <div style={{ fontSize: 22, fontWeight: 900, color: '#8b5cf6' }}>{data.search_queries_analyzed}</div>
              <div style={{ fontSize: 10, color: 'rgba(232,232,232,0.45)' }}>Queries Analyzed</div>
            </div>
          </div>
          {data.gaps?.map((gap, i) => (
            <div key={i} style={{ padding: '10px 14px', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <Badge label={gap.priority} color={priorityColor(gap.priority)} />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#e8e8e8' }}>{gap.query}</div>
                <div style={{ fontSize: 11, color: 'rgba(232,232,232,0.45)', marginTop: 2 }}>{gap.suggested_action}</div>
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#ef4444' }}>~{gap.estimated_monthly_searches?.toLocaleString()}</div>
                <div style={{ fontSize: 10, color: 'rgba(232,232,232,0.35)' }}>searches/mo</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// STATUS HEADER
// ─────────────────────────────────────────────────────────────────────────────

function StatusHeader({ token }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    vertexHealth(token)
      .then(r => setStatus(r.data))
      .catch(() => setStatus({ ok: false, reason: 'Could not reach API' }))
      .finally(() => setLoading(false));
  }, [token]);

  const services = status?.services || [];

  return (
    <div style={{ background: 'linear-gradient(135deg, rgba(139,92,246,0.12), rgba(59,130,246,0.08))', border: '1px solid rgba(139,92,246,0.25)', borderRadius: 16, padding: 20, marginBottom: 24 }}>
      <div className="flex items-center gap-3 mb-4">
        <div style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(139,92,246,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Cpu size={18} color="#8b5cf6" />
        </div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 800, color: '#e8e8e8' }}>Vertex AI Studio</div>
          <div style={{ fontSize: 12, color: 'rgba(232,232,232,0.5)' }}>Powered by GEMINI_API_KEY · text-embedding-004 · gemini-2.5-flash-preview-05-20</div>
        </div>
        {loading ? <Loader2 size={16} className="animate-spin ml-auto" color="#8b5cf6" /> : (
          <div className="ml-auto flex items-center gap-2">
            {status?.ok ? <CheckCircle size={16} color="#10b981" /> : <AlertTriangle size={16} color="#ef4444" />}
            <span style={{ fontSize: 13, fontWeight: 700, color: status?.ok ? '#10b981' : '#ef4444' }}>
              {status?.ok ? 'All Systems Active' : status?.reason || 'Offline'}
            </span>
          </div>
        )}
      </div>
      {services.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {services.map(s => (
            <span key={s} style={{ background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.25)', color: '#34d399', borderRadius: 20, padding: '2px 10px', fontSize: 11, fontWeight: 600 }}>
              ✓ {s.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
      )}
      {status && !status.ok && (
        <div style={{ marginTop: 10, padding: 12, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 10, fontSize: 12, color: '#fca5a5', lineHeight: 1.8 }}>
          <strong style={{ color: '#f87171', display: 'block', marginBottom: 6 }}>⚠ GEMINI_API_KEY is missing or invalid</strong>
          Add one of these to Replit Secrets as <code style={{ background: 'rgba(255,255,255,0.08)', padding: '1px 5px', borderRadius: 4 }}>GEMINI_API_KEY</code>, then restart the API:
          <br /><br />
          <strong style={{ color: '#e8e8e8' }}>Option A — Google AI Studio key</strong> (free, instant)
          <br />
          Get it at <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" style={{ color: '#818cf8', textDecoration: 'underline' }}>aistudio.google.com/app/apikey</a> · starts with <code style={{ background: 'rgba(255,255,255,0.08)', padding: '1px 5px', borderRadius: 4 }}>AIza...</code>
          <br /><br />
          <strong style={{ color: '#e8e8e8' }}>Option B — Vertex AI service account JSON</strong>
          <br />
          Paste the full JSON from Google Cloud Console → IAM → Service Accounts. Must have the <em>Vertex AI User</em> role.
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN COMPONENT
// ─────────────────────────────────────────────────────────────────────────────

const SERVICE_CARDS = [
  { id: 'semantic',  label: 'Semantic Search',   icon: Search,      color: '#3b82f6',  component: SemanticSearchCard },
  { id: 'translate', label: 'Translation',        icon: Languages,   color: '#10b981',  component: TranslationCard },
  { id: 'quality',   label: 'Quality Scorer',     icon: BarChart2,   color: '#f59e0b',  component: QualityScoreCard },
  { id: 'topics',    label: 'Topic Suggester',    icon: Lightbulb,   color: '#a855f7',  component: TopicSuggesterCard },
  { id: 'seo',       label: 'SEO Meta Generator', icon: TrendingUp,  color: '#06b6d4',  component: SeoMetaCard },
  { id: 'gaps',      label: 'Content Gaps',       icon: FileSearch,  color: '#ef4444',  component: ContentGapsCard },
];

export default function AdminVertexPanel({ token, adminToken, onNavigate }) {
  const tk = adminToken || token;
  const [active, setActive] = useState('semantic');

  const ActiveCard = SERVICE_CARDS.find(s => s.id === active)?.component;

  return (
    <div style={{ padding: '0 2px' }}>
      <StatusHeader token={tk} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 24 }}>
        {SERVICE_CARDS.map(s => {
          const Icon = s.icon;
          const isActive = active === s.id;
          return (
            <button key={s.id} onClick={() => setActive(s.id)}
              style={{
                background: isActive ? `${s.color}18` : 'rgba(255,255,255,0.025)',
                border: `1px solid ${isActive ? s.color + '55' : 'rgba(255,255,255,0.08)'}`,
                borderRadius: 12, padding: '10px 14px', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 8, transition: 'all 0.15s',
                textAlign: 'left',
              }}>
              <Icon size={15} color={isActive ? s.color : 'rgba(232,232,232,0.4)'} />
              <span style={{ fontSize: 12, fontWeight: 700, color: isActive ? s.color : 'rgba(232,232,232,0.55)' }}>
                {s.label}
              </span>
            </button>
          );
        })}
      </div>

      {ActiveCard && <ActiveCard token={tk} onNavigate={onNavigate} />}

      <div style={{ marginTop: 24, padding: 16, background: 'rgba(139,92,246,0.05)', border: '1px solid rgba(139,92,246,0.15)', borderRadius: 12 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#8b5cf6', marginBottom: 8, textTransform: 'uppercase' }}>Also Available In Other Panels</div>
        <div style={{ fontSize: 12, color: 'rgba(232,232,232,0.5)', lineHeight: 1.8 }}>
          • <strong style={{ color: '#e8e8e8' }}>CMS Editor</strong> — Translate button on any document<br />
          • <strong style={{ color: '#e8e8e8' }}>Content Studio</strong> — Enhance + Quality Score on generated blocks<br />
          • <strong style={{ color: '#e8e8e8' }}>Thumbnail Studio</strong> — Gemini Vision analysis (replaces Groq)<br />
          • <strong style={{ color: '#e8e8e8' }}>Document Upload</strong> — Extract topics/MCQs from AHSEC PDFs
        </div>
      </div>
    </div>
  );
}
