import { useState, useEffect, useMemo, useRef } from 'react';
import {
  Loader2, MessageSquare, BookOpen, Search, Mail, User, Ghost,
  ChevronRight, Crown, X, Clock, ArrowLeft, Sparkles, SmilePlus, Frown, Meh, TrendingUp, RefreshCw,
} from 'lucide-react';
import AdminQuickLinks from './AdminQuickLinks';
import { adminGetConversations, extractFaqs, conversationsSentiment, syncConversations } from '@/utils/api';
import { toast } from 'sonner';
import { formatDistanceToNow, format } from 'date-fns';

const PLAN_COLORS = {
  free: 'text-slate-400 bg-slate-400/10 border-slate-400/20',
  starter: 'text-violet-400 bg-violet-400/10 border-violet-400/20',
  pro: 'text-amber-400 bg-amber-400/10 border-amber-400/20',
};

function UserAvatar({ name, avatar, size = 32, isAnonymous = false }) {
  if (isAnonymous) {
    return (
      <div
        className="rounded-lg flex items-center justify-center flex-shrink-0"
        style={{ width: size, height: size, background: 'linear-gradient(135deg, #475569, #64748b)' }}
      >
        <Ghost size={size * 0.5} color="#cbd5e1" />
      </div>
    );
  }
  const initials = (name || 'U').split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
  if (avatar) {
    return <img src={avatar} alt="" className="rounded-lg object-cover flex-shrink-0" style={{ width: size, height: size }} />;
  }
  return (
    <div
      className="rounded-lg flex items-center justify-center font-bold text-white flex-shrink-0"
      style={{ width: size, height: size, fontSize: size * 0.35, background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)' }}
    >
      {initials}
    </div>
  );
}

function SentimentBar({ data }) {
  if (!data || !data.total) return null;
  const { positive_pct, negative_pct, positive, negative, neutral, total } = data;
  return (
    <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 12, padding: '12px 16px' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'rgba(232,232,232,0.4)', textTransform: 'uppercase', marginBottom: 8 }}>Sentiment Analysis ({total} messages)</div>
      <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', gap: 1 }}>
        <div style={{ flex: positive, background: '#10b981' }} title={`Positive: ${positive_pct}%`} />
        <div style={{ flex: Math.max(0, total - positive - negative), background: '#64748b' }} title={`Neutral`} />
        <div style={{ flex: negative, background: '#ef4444' }} title={`Negative: ${negative_pct}%`} />
      </div>
      <div style={{ display: 'flex', gap: 16, marginTop: 6 }}>
        {[
          { label: 'Positive', value: positive, pct: positive_pct, color: '#10b981' },
          { label: 'Neutral', value: neutral, color: '#64748b' },
          { label: 'Negative', value: negative, pct: negative_pct, color: '#ef4444' },
        ].map(s => (
          <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: s.color }} />
            <span style={{ fontSize: 11, color: 'rgba(232,232,232,0.5)' }}>{s.label}: <strong style={{ color: s.color }}>{s.value}</strong> {s.pct !== undefined ? `(${s.pct}%)` : ''}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AdminConversations({ adminToken, onNavigate }) {
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [search, setSearch] = useState('');
  const [tab, setTab] = useState('conversations'); // 'conversations' | 'faqs'
  const [faqs, setFaqs] = useState(null);
  const [faqLoading, setFaqLoading] = useState(false);
  const [sentiment, setSentiment] = useState(null);
  const [filterMode, setFilterMode] = useState('all'); // 'all' | 'with_messages' | 'anonymous' | 'registered'
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);
  const chatEndRef = useRef(null);

  const loadConversations = (token) => {
    setLoading(true);
    adminGetConversations(token)
      .then((res) => setConversations(res.data))
      .catch(() => toast.error('Failed to load conversations'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadConversations(adminToken);
    conversationsSentiment(adminToken).then(r => setSentiment(r.data)).catch(() => {});
  }, [adminToken]);

  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const r = await syncConversations(adminToken);
      const d = r.data;
      setSyncResult(d);
      toast.success(`Sync complete — ${d.inserted} inserted, ${d.updated} updated, ${d.skipped} unchanged. PG now has ${d.pg_with_messages_after} conversations with ${d.pg_total_messages_after} messages.`);
      loadConversations(adminToken);
    } catch (err) {
      toast.error('Sync failed: ' + (err?.response?.data?.detail || err.message));
    } finally {
      setSyncing(false);
    }
  };

  const handleExtractFaqs = async () => {
    setFaqLoading(true);
    setTab('faqs');
    try {
      const r = await extractFaqs(adminToken, 150);
      setFaqs(r.data);
      toast.success(`Extracted ${r.data.faqs?.length || 0} FAQs from ${r.data.total_questions_analyzed} questions`);
    } catch {
      toast.error('FAQ extraction failed');
    } finally { setFaqLoading(false); }
  };

  const totalMessages = useMemo(() => conversations.reduce((sum, c) => sum + (c.messages || []).length, 0), [conversations]);
  const withMessages = useMemo(() => conversations.filter(c => (c.messages || []).length > 0), [conversations]);
  const anonymousConvs = useMemo(() => conversations.filter(c => c.is_anonymous), [conversations]);
  const registeredConvs = useMemo(() => conversations.filter(c => !c.is_anonymous), [conversations]);

  const filtered = useMemo(() => {
    let base = conversations;
    if (filterMode === 'with_messages') base = withMessages;
    else if (filterMode === 'anonymous') base = anonymousConvs;
    else if (filterMode === 'registered') base = registeredConvs;
    if (!search.trim()) return base;
    const q = search.toLowerCase();
    return base.filter((c) =>
      (c.title || '').toLowerCase().includes(q) ||
      (c.subject_name || '').toLowerCase().includes(q) ||
      (c.user_email || '').toLowerCase().includes(q) ||
      (c.user_name || '').toLowerCase().includes(q) ||
      (c.messages || []).some(m => (m.content || '').toLowerCase().includes(q))
    );
  }, [conversations, withMessages, anonymousConvs, registeredConvs, search, filterMode]);

  const selectedConv = useMemo(() => conversations.find(c => c.id === selected), [conversations, selected]);

  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [selected, selectedConv?.messages?.length]);

  if (loading) return <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-slate-400" /></div>;

  const IMPORTANCE_COLOR = { high: '#ef4444', medium: '#f59e0b', low: '#10b981' };

  return (
    <div className="flex flex-col h-full" style={{ minHeight: 'calc(100vh - 120px)' }}>
      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, padding: '8px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)', alignItems: 'center' }}>
        {[
          { id: 'conversations', label: `Conversations (${conversations.length})` },
          { id: 'faqs', label: 'FAQ Extractor' },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            style={{ padding: '5px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: 'none', background: tab === t.id ? '#7c3aed' : 'rgba(255,255,255,0.04)', color: tab === t.id ? '#fff' : 'rgba(232,232,232,0.45)' }}>
            {t.label}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <button onClick={handleSync} disabled={syncing}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', borderRadius: 8, fontSize: 11, fontWeight: 700, cursor: 'pointer', border: '1px solid rgba(16,185,129,0.3)', background: 'rgba(16,185,129,0.08)', color: '#34d399' }}>
          {syncing ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
          {syncing ? 'Syncing…' : 'Sync Supabase → PG'}
        </button>
        <button onClick={handleExtractFaqs} disabled={faqLoading}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', borderRadius: 8, fontSize: 11, fontWeight: 700, cursor: 'pointer', border: '1px solid rgba(139,92,246,0.3)', background: 'rgba(139,92,246,0.1)', color: '#a78bfa' }}>
          {faqLoading ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />} Extract FAQs
        </button>
      </div>

      {/* FAQ Tab */}
      {tab === 'faqs' && (
        <div className="p-6 space-y-4 flex-1 overflow-y-auto">
          <SentimentBar data={sentiment} />
          {faqLoading ? (
            <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-violet-400" /></div>
          ) : faqs ? (
            <>
              <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 12, padding: 16 }}>
                <div className="flex items-center gap-2 mb-1">
                  <Sparkles size={14} color="#a78bfa" />
                  <span style={{ color: '#e8e8e8', fontWeight: 700, fontSize: 14 }}>AI-Extracted FAQs</span>
                </div>
                <p style={{ color: 'rgba(232,232,232,0.45)', fontSize: 12 }}>
                  {faqs.faqs?.length || 0} FAQs from {faqs.total_questions_analyzed} student questions
                  {faqs.subjects?.length > 0 && ` · Subjects: ${faqs.subjects.slice(0,5).join(', ')}`}
                </p>
              </div>
              <div className="space-y-2">
                {(faqs.faqs || []).map((faq, i) => (
                  <div key={i} style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 10, padding: '10px 14px', display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                    <div style={{ width: 24, height: 24, borderRadius: 6, background: 'rgba(139,92,246,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 11, color: '#a78bfa', flexShrink: 0 }}>{i + 1}</div>
                    <div style={{ flex: 1 }}>
                      <p style={{ fontSize: 13, color: '#e8e8e8', fontWeight: 500, lineHeight: 1.5 }}>{faq.question || faq}</p>
                      {faq.category && <p style={{ fontSize: 11, color: 'rgba(232,232,232,0.35)', marginTop: 3 }}>Category: {faq.category}</p>}
                    </div>
                    {faq.importance && (
                      <span style={{ fontSize: 10, fontWeight: 800, padding: '2px 7px', borderRadius: 20, background: `${IMPORTANCE_COLOR[faq.importance]}22`, color: IMPORTANCE_COLOR[faq.importance], flexShrink: 0 }}>
                        {faq.importance}
                      </span>
                    )}
                  </div>
                ))}
              </div>
              {faqs.suggested_pages?.length > 0 && (
                <div style={{ background: 'rgba(16,185,129,0.05)', border: '1px solid rgba(16,185,129,0.15)', borderRadius: 12, padding: 14 }}>
                  <p style={{ fontSize: 11, fontWeight: 700, color: '#10b981', marginBottom: 8, textTransform: 'uppercase' }}>Suggested SEO Pages</p>
                  {faqs.suggested_pages.slice(0, 8).map((p, i) => (
                    <div key={i} style={{ fontSize: 12, color: 'rgba(232,232,232,0.5)', padding: '3px 0', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                      → {p.title} <span style={{ color: '#10b981' }}>({p.priority})</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: 60 }}>
              <Sparkles size={32} color="rgba(139,92,246,0.25)" style={{ margin: '0 auto 12px' }} />
              <p style={{ color: 'rgba(232,232,232,0.4)', fontSize: 13 }}>Click "Extract FAQs" to analyse student questions with AI</p>
            </div>
          )}
        </div>
      )}

      {/* Conversations Tab */}
      {tab === 'conversations' && (
      <div className="flex flex-1 min-h-0">
      {/* Left: Conversation list */}
      <div className={`${selected ? 'hidden lg:flex' : 'flex'} flex-col w-full lg:w-[380px] lg:min-w-[380px] border-r border-white/[0.06]`}>
        <div className="p-4 border-b border-white/[0.06] space-y-3">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h2 className="text-slate-200 font-semibold">Conversations ({conversations.length})</h2>
              <p className="text-xs text-slate-500">{withMessages.length} with messages · {totalMessages} total msgs · {anonymousConvs.length} anonymous</p>
            </div>
            <div className="flex gap-1 flex-shrink-0">
              {[
                { id: 'all', label: 'All' },
                { id: 'with_messages', label: 'With msgs' },
                { id: 'anonymous', label: `Anon (${anonymousConvs.length})` },
                { id: 'registered', label: 'Registered' },
              ].map(f => (
                <button key={f.id} onClick={() => setFilterMode(f.id)}
                  style={{ padding: '3px 10px', borderRadius: 6, fontSize: 10, fontWeight: 700, cursor: 'pointer', border: 'none',
                    background: filterMode === f.id ? '#7c3aed' : 'rgba(255,255,255,0.05)',
                    color: filterMode === f.id ? '#fff' : 'rgba(232,232,232,0.4)' }}>
                  {f.label}
                </button>
              ))}
            </div>
          </div>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              placeholder="Search name, email, title, subject..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm bg-slate-900 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-500"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {filtered.length === 0 && (
            <div className="text-center py-12 text-slate-600">
              <MessageSquare size={32} className="mx-auto mb-2 opacity-30" />
              <p className="text-sm">{search ? 'No conversations match' : 'No conversations yet'}</p>
            </div>
          )}
          {filtered.map((conv) => {
            const msgCount = (conv.messages || []).length;
            const hasMsgs = msgCount > 0;
            return (
            <div
              key={conv.id}
              onClick={() => setSelected(conv.id)}
              className={`flex items-start gap-3 p-4 cursor-pointer border-b border-white/[0.04] transition-colors ${
                selected === conv.id ? 'bg-violet-500/10 border-l-2 border-l-violet-500' : 'hover:bg-white/[0.03]'
              }`}
            >
              <UserAvatar name={conv.user_name} avatar={conv.user_avatar} size={36} isAnonymous={conv.is_anonymous} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium text-slate-200 truncate">{conv.title || 'Untitled'}</p>
                  <span className="text-[10px] text-slate-500 flex-shrink-0">
                    {formatDistanceToNow(new Date(conv.updated_at || conv.created_at), { addSuffix: true })}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <p className="text-xs text-slate-400 truncate">{conv.is_anonymous ? 'Anonymous User' : (conv.user_name || 'Unknown')}</p>
                  {conv.is_anonymous && (
                    <span style={{ fontSize: 9, fontWeight: 800, padding: '1px 6px', borderRadius: 20, background: 'rgba(100,116,139,0.2)', color: '#94a3b8', border: '1px solid rgba(100,116,139,0.3)' }}>
                      Anonymous
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1 text-[10px]">
                  {conv.subject_name && <span className="text-slate-500 truncate">{conv.subject_name}</span>}
                  {hasMsgs ? (
                    <span style={{ color: '#10b981', fontWeight: 700 }}>{msgCount} msgs</span>
                  ) : (
                    <span style={{ color: 'rgba(232,232,232,0.2)', fontStyle: 'italic' }}>no messages</span>
                  )}
                </div>
              </div>
            </div>
            );
          })}
        </div>
      </div>

      {/* Right: Chat detail / placeholder */}
      <div className={`${selected ? 'flex' : 'hidden lg:flex'} flex-col flex-1 min-w-0`}>
        {!selectedConv ? (
          <div className="flex-1 flex items-center justify-center text-slate-600">
            <div className="text-center">
              <MessageSquare size={48} className="mx-auto mb-3 opacity-20" />
              <p className="text-sm">Select a conversation to view</p>
            </div>
          </div>
        ) : (
          <>
            {/* Chat header with user profile */}
            <div className="p-4 border-b border-white/[0.06]">
              <div className="flex items-start gap-3">
                <button
                  onClick={() => setSelected(null)}
                  className="lg:hidden p-1.5 rounded-lg hover:bg-white/10 text-slate-400 mt-1"
                >
                  <ArrowLeft size={16} />
                </button>
                <UserAvatar name={selectedConv.user_name} avatar={selectedConv.user_avatar} size={44} isAnonymous={selectedConv.is_anonymous} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold text-white truncate">{selectedConv.is_anonymous ? 'Anonymous User' : (selectedConv.user_name || 'Unknown User')}</h3>
                    {selectedConv.is_anonymous ? (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border text-slate-400 bg-slate-400/10 border-slate-400/20">
                        <Ghost size={8} />
                        Anonymous
                      </span>
                    ) : (
                      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border ${PLAN_COLORS[selectedConv.user_plan] || PLAN_COLORS.free}`}>
                        <Crown size={8} />
                        {(selectedConv.user_plan || 'free').charAt(0).toUpperCase() + (selectedConv.user_plan || 'free').slice(1)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-slate-500 mt-0.5 flex-wrap">
                    {selectedConv.is_anonymous ? (
                      <span className="flex items-center gap-1 text-slate-500">
                        <Ghost size={10} />
                        ID: {selectedConv.anon_id?.slice(0, 12)}…
                      </span>
                    ) : (
                      <>
                        {selectedConv.user_email && (
                          <span className="flex items-center gap-1"><Mail size={10} />{selectedConv.user_email}</span>
                        )}
                        {selectedConv.user_board && (
                          <span>{selectedConv.user_board}</span>
                        )}
                        {selectedConv.user_class && (
                          <span>{selectedConv.user_class}</span>
                        )}
                        {selectedConv.user_stream && (
                          <span>{selectedConv.user_stream}</span>
                        )}
                      </>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-slate-500 mt-1">
                    <span className="font-medium text-slate-300 truncate">{selectedConv.title || 'Untitled'}</span>
                    {selectedConv.subject_name && (
                      <span className="flex items-center gap-1"><BookOpen size={10} />{selectedConv.subject_name}</span>
                    )}
                    <span className="flex items-center gap-1">
                      <Clock size={10} />
                      {format(new Date(selectedConv.created_at || selectedConv.updated_at), 'MMM d, yyyy h:mm a')}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Chat messages - full content */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {(selectedConv.messages || []).map((msg, i) => (
                <div
                  key={i}
                  className={`flex gap-3 ${msg.role === 'user' ? '' : ''}`}
                >
                  <div className="flex-shrink-0 mt-1">
                    {msg.role === 'user' ? (
                      <UserAvatar name={selectedConv.user_name} avatar={selectedConv.user_avatar} size={28} isAnonymous={selectedConv.is_anonymous} />
                    ) : (
                      <div className="w-7 h-7 rounded-lg overflow-hidden flex-shrink-0 bg-violet-600 flex items-center justify-center">
                        <img
                          src={`${import.meta.env.BASE_URL}logo.webp`}
                          alt="Syra"
                          className="w-full h-full object-cover"
                          onError={e => { e.currentTarget.style.display = 'none'; }}
                        />
                      </div>
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-xs font-semibold ${msg.role === 'user' ? 'text-blue-400' : 'text-violet-400'}`}>
                        {msg.role === 'user' ? (selectedConv.is_anonymous ? 'Anonymous User' : (selectedConv.user_name || 'Student')) : 'Syra AI'}
                      </span>
                      {msg.timestamp && (
                        <span className="text-[10px] text-slate-600">
                          {format(new Date(msg.timestamp), 'h:mm a')}
                        </span>
                      )}
                    </div>
                    <div
                      className={`text-sm rounded-xl px-3.5 py-2.5 ${
                        msg.role === 'user'
                          ? 'bg-slate-800 text-slate-200'
                          : 'bg-violet-900/15 text-slate-300 border border-violet-500/10'
                      }`}
                      style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                    >
                      {msg.content}
                    </div>
                  </div>
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* Chat footer */}
            <div className="p-3 border-t border-white/[0.06] text-center">
              <p className="text-[10px] text-slate-600">
                {(selectedConv.messages || []).length} messages · Conversation ID: {selectedConv.id?.slice(0, 8)}...
              </p>
            </div>
          </>
        )}
      </div>
      </div>
      )}
      <AdminQuickLinks links={['users','analytics','dashboard','vertex']} onNavigate={onNavigate} />
    </div>
  );
}
