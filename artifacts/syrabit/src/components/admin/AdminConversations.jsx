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
  free: 'text-white/40 bg-white/[0.06] border-white/[0.08]',
  starter: 'text-violet-400 bg-violet-400/10 border-violet-400/20',
  pro: 'text-amber-400 bg-amber-400/10 border-amber-400/20',
};

function UserAvatar({ name, avatar, size = 32, isAnonymous = false }) {
  if (isAnonymous) {
    return (
      <div
        className="rounded-lg flex items-center justify-center flex-shrink-0"
        style={{ width: size, height: size, background: 'linear-gradient(135deg, rgba(255,255,255,0.06), rgba(255,255,255,0.12))' }}
      >
        <Ghost size={size * 0.5} color="rgba(255,255,255,0.4)" />
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
    <div className="rounded-xl p-4" style={{ background: 'rgba(15,15,30,0.6)', border: '1px solid rgba(255,255,255,0.06)' }}>
      <div className="text-[11px] font-bold text-white/25 uppercase mb-2">Sentiment Analysis ({total} messages)</div>
      <div className="flex h-2 rounded-full overflow-hidden gap-0.5">
        <div style={{ flex: positive, background: '#10b981' }} title={`Positive: ${positive_pct}%`} />
        <div style={{ flex: Math.max(0, total - positive - negative), background: 'rgba(255,255,255,0.15)' }} title={`Neutral`} />
        <div style={{ flex: negative, background: '#ef4444' }} title={`Negative: ${negative_pct}%`} />
      </div>
      <div className="flex gap-4 mt-2">
        {[
          { label: 'Positive', value: positive, pct: positive_pct, color: '#10b981' },
          { label: 'Neutral', value: neutral, color: 'rgba(255,255,255,0.3)' },
          { label: 'Negative', value: negative, pct: negative_pct, color: '#ef4444' },
        ].map(s => (
          <div key={s.label} className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full" style={{ background: s.color }} />
            <span className="text-[11px] text-white/30">{s.label}: <strong style={{ color: s.color }}>{s.value}</strong> {s.pct !== undefined ? `(${s.pct}%)` : ''}</span>
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
  const [tab, setTab] = useState('conversations');
  const [faqs, setFaqs] = useState(null);
  const [faqLoading, setFaqLoading] = useState(false);
  const [sentiment, setSentiment] = useState(null);
  const [filterMode, setFilterMode] = useState('all');
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

  if (loading) return <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-violet-400/60" /></div>;

  const IMPORTANCE_COLOR = { high: '#ef4444', medium: '#f59e0b', low: '#10b981' };

  return (
    <div className="flex flex-col h-full" style={{ minHeight: 'calc(100vh - 120px)' }}>
      <div className="flex gap-1.5 px-4 py-2 items-center" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        {[
          { id: 'conversations', label: `Conversations (${conversations.length})` },
          { id: 'faqs', label: 'FAQ Extractor' },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className="px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all"
            style={tab === t.id
              ? { background: 'linear-gradient(135deg, #7c3aed, #6d28d9)', color: '#fff', boxShadow: '0 2px 12px rgba(124,58,237,0.3)' }
              : { background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.35)' }
            }>
            {t.label}
          </button>
        ))}
        <div className="flex-1" />
        <button onClick={handleSync} disabled={syncing}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold transition-all"
          style={{ border: '1px solid rgba(16,185,129,0.2)', background: 'rgba(16,185,129,0.06)', color: '#34d399' }}>
          {syncing ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
          {syncing ? 'Syncing…' : 'Sync Supabase → PG'}
        </button>
        <button onClick={handleExtractFaqs} disabled={faqLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold transition-all"
          style={{ border: '1px solid rgba(139,92,246,0.2)', background: 'rgba(139,92,246,0.08)', color: '#a78bfa' }}>
          {faqLoading ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />} Extract FAQs
        </button>
      </div>

      {tab === 'faqs' && (
        <div className="p-6 space-y-4 flex-1 overflow-y-auto">
          <SentimentBar data={sentiment} />
          {faqLoading ? (
            <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-violet-400" /></div>
          ) : faqs ? (
            <>
              <div className="rounded-xl p-4" style={{ background: 'rgba(15,15,30,0.6)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div className="flex items-center gap-2 mb-1">
                  <Sparkles size={14} color="#a78bfa" />
                  <span className="text-white/90 font-bold text-sm">AI-Extracted FAQs</span>
                </div>
                <p className="text-white/30 text-xs">
                  {faqs.faqs?.length || 0} FAQs from {faqs.total_questions_analyzed} student questions
                  {faqs.subjects?.length > 0 && ` · Subjects: ${faqs.subjects.slice(0,5).join(', ')}`}
                </p>
              </div>
              <div className="space-y-2">
                {(faqs.faqs || []).map((faq, i) => (
                  <div key={i} className="flex items-start gap-3 rounded-xl p-3" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                    <div className="w-6 h-6 rounded-lg flex items-center justify-center font-extrabold text-[11px] text-violet-400 flex-shrink-0" style={{ background: 'rgba(139,92,246,0.12)' }}>{i + 1}</div>
                    <div className="flex-1">
                      <p className="text-sm text-white/80 font-medium leading-relaxed">{faq.question || faq}</p>
                      {faq.category && <p className="text-[11px] text-white/20 mt-1">Category: {faq.category}</p>}
                    </div>
                    {faq.importance && (
                      <span className="text-[10px] font-extrabold px-2 py-0.5 rounded-full flex-shrink-0" style={{ background: `${IMPORTANCE_COLOR[faq.importance]}18`, color: IMPORTANCE_COLOR[faq.importance] }}>
                        {faq.importance}
                      </span>
                    )}
                  </div>
                ))}
              </div>
              {faqs.suggested_pages?.length > 0 && (
                <div className="rounded-xl p-4" style={{ background: 'rgba(16,185,129,0.04)', border: '1px solid rgba(16,185,129,0.12)' }}>
                  <p className="text-[11px] font-bold text-emerald-400 mb-2 uppercase tracking-wide">Suggested SEO Pages</p>
                  {faqs.suggested_pages.slice(0, 8).map((p, i) => (
                    <div key={i} className="text-xs text-white/35 py-1" style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                      → {p.title} <span className="text-emerald-400">({p.priority})</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="text-center py-16">
              <Sparkles size={32} className="mx-auto mb-3" style={{ color: 'rgba(139,92,246,0.2)' }} />
              <p className="text-white/25 text-sm">Click "Extract FAQs" to analyse student questions with AI</p>
            </div>
          )}
        </div>
      )}

      {tab === 'conversations' && (
      <div className="flex flex-1 min-h-0">
      <div className={`${selected ? 'hidden lg:flex' : 'flex'} flex-col w-full lg:w-[380px] lg:min-w-[380px] border-r border-white/[0.06]`}>
        <div className="p-4 border-b border-white/[0.06] space-y-3">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h2 className="text-white/90 font-semibold">Conversations ({conversations.length})</h2>
              <p className="text-xs text-white/25">{withMessages.length} with messages · {totalMessages} total msgs · {anonymousConvs.length} anonymous</p>
            </div>
            <div className="flex gap-1 flex-shrink-0">
              {[
                { id: 'all', label: 'All' },
                { id: 'with_messages', label: 'With msgs' },
                { id: 'anonymous', label: `Anon (${anonymousConvs.length})` },
                { id: 'registered', label: 'Registered' },
              ].map(f => (
                <button key={f.id} onClick={() => setFilterMode(f.id)}
                  className="px-2.5 py-1 rounded-lg text-[10px] font-bold transition-all"
                  style={filterMode === f.id
                    ? { background: 'linear-gradient(135deg, #7c3aed, #6d28d9)', color: '#fff' }
                    : { background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.3)' }
                  }>
                  {f.label}
                </button>
              ))}
            </div>
          </div>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/25" />
            <input
              type="text"
              placeholder="Search name, email, title, subject..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm rounded-xl text-white/80 placeholder-white/20 focus:outline-none focus:border-violet-500"
              style={{ background: 'rgba(15,15,30,0.6)', border: '1px solid rgba(255,255,255,0.06)' }}
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {filtered.length === 0 && (
            <div className="text-center py-12 text-white/15">
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
                  <p className="text-sm font-medium text-white/80 truncate">{conv.title || 'Untitled'}</p>
                  <span className="text-[10px] text-white/20 flex-shrink-0">
                    {formatDistanceToNow(new Date(conv.updated_at || conv.created_at), { addSuffix: true })}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <p className="text-xs text-white/35 truncate">{conv.is_anonymous ? 'Anonymous User' : (conv.user_name || 'Unknown')}</p>
                  {conv.is_anonymous && (
                    <span className="text-[9px] font-extrabold px-1.5 py-0.5 rounded-full" style={{ background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.35)', border: '1px solid rgba(255,255,255,0.08)' }}>
                      Anonymous
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1 text-[10px]">
                  {conv.subject_name && <span className="text-white/20 truncate">{conv.subject_name}</span>}
                  {hasMsgs ? (
                    <span className="text-emerald-400 font-bold">{msgCount} msgs</span>
                  ) : (
                    <span className="text-white/15 italic">no messages</span>
                  )}
                </div>
              </div>
            </div>
            );
          })}
        </div>
      </div>

      <div className={`${selected ? 'flex' : 'hidden lg:flex'} flex-col flex-1 min-w-0`}>
        {!selectedConv ? (
          <div className="flex-1 flex items-center justify-center text-white/15">
            <div className="text-center">
              <MessageSquare size={48} className="mx-auto mb-3 opacity-20" />
              <p className="text-sm">Select a conversation to view</p>
            </div>
          </div>
        ) : (
          <>
            <div className="p-4 border-b border-white/[0.06]">
              <div className="flex items-start gap-3">
                <button
                  onClick={() => setSelected(null)}
                  className="lg:hidden p-1.5 rounded-lg hover:bg-white/10 text-white/30 mt-1"
                >
                  <ArrowLeft size={16} />
                </button>
                <UserAvatar name={selectedConv.user_name} avatar={selectedConv.user_avatar} size={44} isAnonymous={selectedConv.is_anonymous} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold text-white truncate">{selectedConv.is_anonymous ? 'Anonymous User' : (selectedConv.user_name || 'Unknown User')}</h3>
                    {selectedConv.is_anonymous ? (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border text-white/40 bg-white/[0.06] border-white/[0.08]">
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
                  <div className="flex items-center gap-3 text-xs text-white/25 mt-0.5 flex-wrap">
                    {selectedConv.is_anonymous ? (
                      <span className="flex items-center gap-1">
                        <Ghost size={10} />
                        ID: {selectedConv.anon_id?.slice(0, 12)}…
                      </span>
                    ) : (
                      <>
                        {selectedConv.user_email && (
                          <span className="flex items-center gap-1"><Mail size={10} />{selectedConv.user_email}</span>
                        )}
                        {selectedConv.user_board && <span>{selectedConv.user_board}</span>}
                        {selectedConv.user_class && <span>{selectedConv.user_class}</span>}
                        {selectedConv.user_stream && <span>{selectedConv.user_stream}</span>}
                      </>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-white/25 mt-1">
                    <span className="font-medium text-white/60 truncate">{selectedConv.title || 'Untitled'}</span>
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

            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {(selectedConv.messages || []).map((msg, i) => (
                <div key={i} className="flex gap-3">
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
                        <span className="text-[10px] text-white/15">
                          {format(new Date(msg.timestamp), 'h:mm a')}
                        </span>
                      )}
                    </div>
                    <div
                      className="text-sm rounded-xl px-3.5 py-2.5"
                      style={msg.role === 'user'
                        ? { background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.7)' }
                        : { background: 'rgba(139,92,246,0.08)', color: 'rgba(255,255,255,0.65)', border: '1px solid rgba(139,92,246,0.1)' }
                      }
                    >
                      <span style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{msg.content}</span>
                    </div>
                  </div>
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>

            <div className="p-3 border-t border-white/[0.06] text-center">
              <p className="text-[10px] text-white/15">
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
