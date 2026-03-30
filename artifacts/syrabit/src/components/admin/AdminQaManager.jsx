import { useState, useEffect, useCallback } from 'react';
import { MessageSquare, CheckCircle2, Trash2, Plus, RefreshCw,
  ChevronDown, ChevronUp, ArrowUpCircle, Search, Loader2, BookOpen, EyeOff } from 'lucide-react';
import { toast } from 'sonner';
import {
  adminListChatMessages, adminListQaPairs, adminCreateQaPair,
  adminUpdateQaStatus, adminDeleteQaPair, adminPromoteChatToQa,
} from '@/utils/api';

const STATUS_STYLE = {
  published: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
  draft:     'text-amber-400  bg-amber-400/10  border-amber-400/20',
  deleted:   'text-red-400    bg-red-400/10    border-red-400/20',
};

function Collapse({ question, answer, expanded, onToggle }) {
  return (
    <div className="border border-white/8 rounded-xl overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-start justify-between gap-3 px-4 py-3 text-left hover:bg-white/3 transition-colors"
      >
        <span className="text-sm text-white font-medium flex-1">{question}</span>
        {expanded ? <ChevronUp size={14} className="text-white/30 shrink-0 mt-0.5" /> : <ChevronDown size={14} className="text-white/30 shrink-0 mt-0.5" />}
      </button>
      {expanded && (
        <div className="px-4 pb-4 text-sm text-white/50 leading-relaxed border-t border-white/6 pt-3 whitespace-pre-wrap">
          {answer}
        </div>
      )}
    </div>
  );
}

export default function AdminQaManager({ adminToken }) {
  const [tab, setTab]       = useState('chat');
  const [loading, setLoading] = useState(false);

  // Chat logs state
  const [chatMsgs, setChatMsgs]   = useState([]);
  const [chatSearch, setChatSearch] = useState('');
  const [expandedChat, setExpandedChat] = useState(new Set());
  const [promoting, setPromoting]   = useState(new Set());

  // QA pairs state
  const [pairs, setPairs]         = useState([]);
  const [pairSearch, setPairSearch] = useState('');
  const [pairFilter, setPairFilter] = useState('all');
  const [expandedQa, setExpandedQa] = useState(new Set());

  // Create QA form
  const [showCreate, setShowCreate] = useState(false);
  const [newQ, setNewQ]   = useState('');
  const [newA, setNewA]   = useState('');
  const [newBoard, setNewBoard]   = useState('');
  const [newClass, setNewClass]   = useState('');
  const [newSubject, setNewSubject] = useState('');
  const [newTopic, setNewTopic]   = useState('');
  const [creating, setCreating]   = useState(false);

  const loadChatMessages = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminListChatMessages(adminToken, { limit: 100, promoted: false });
      setChatMsgs(res.data?.messages || []);
    } catch { toast.error('Failed to load chat logs'); }
    finally { setLoading(false); }
  }, [adminToken]);

  const loadQaPairs = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (pairFilter !== 'all') params.status = pairFilter;
      const res = await adminListQaPairs(adminToken, params);
      setPairs(res.data?.qa_pairs || []);
    } catch { toast.error('Failed to load QA pairs'); }
    finally { setLoading(false); }
  }, [adminToken, pairFilter]);

  useEffect(() => { if (tab === 'chat') loadChatMessages(); else loadQaPairs(); }, [tab, loadChatMessages, loadQaPairs]);

  const handlePromote = async (msg) => {
    setPromoting((p) => new Set([...p, msg.id]));
    try {
      await adminPromoteChatToQa(adminToken, msg.id);
      toast.success('Promoted to QA pair (draft) — go to QA Pairs tab');
      setChatMsgs((prev) => prev.filter((m) => m.id !== msg.id));
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Promote failed');
    } finally {
      setPromoting((p) => { const n = new Set(p); n.delete(msg.id); return n; });
    }
  };

  const handleToggleStatus = async (pair) => {
    const next = pair.status === 'published' ? 'draft' : 'published';
    try {
      await adminUpdateQaStatus(adminToken, pair.id, next);
      setPairs((prev) => prev.map((p) => p.id === pair.id ? { ...p, status: next } : p));
      toast.success(next === 'published' ? 'Published' : 'Unpublished');
    } catch { toast.error('Update failed'); }
  };

  const handleDelete = async (pair) => {
    toast(`Delete "${pair.question.slice(0, 60)}…"?`, {
      action: { label: 'Delete', onClick: async () => {
        try {
          await adminDeleteQaPair(adminToken, pair.id);
          setPairs((prev) => prev.filter((p) => p.id !== pair.id));
          toast.success('Deleted');
        } catch { toast.error('Delete failed'); }
      }},
      cancel: { label: 'Cancel', onClick: () => {} },
    });
  };

  const handleCreate = async () => {
    if (!newQ.trim() || !newA.trim()) { toast.error('Question and answer required'); return; }
    setCreating(true);
    try {
      const res = await adminCreateQaPair(adminToken, {
        question: newQ, answer: newA,
        board_slug: newBoard, class_slug: newClass,
        subject_slug: newSubject, topic_slug: newTopic,
      });
      toast.success('QA pair created (draft)');
      setPairs((prev) => [res.data, ...prev]);
      setShowCreate(false);
      setNewQ(''); setNewA(''); setNewBoard(''); setNewClass(''); setNewSubject(''); setNewTopic('');
      setTab('pairs');
    } catch { toast.error('Create failed'); }
    finally { setCreating(false); }
  };

  const toggleChatExpand = (id) => setExpandedChat((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const toggleQaExpand   = (id) => setExpandedQa((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const filteredChat = chatMsgs.filter((m) =>
    !chatSearch || m.question?.toLowerCase().includes(chatSearch.toLowerCase()) ||
    m.subject_name?.toLowerCase().includes(chatSearch.toLowerCase())
  );

  const filteredPairs = pairs.filter((p) => {
    if (pairFilter !== 'all' && p.status !== pairFilter) return false;
    if (!pairSearch) return true;
    return p.question?.toLowerCase().includes(pairSearch.toLowerCase()) ||
      p.answer?.toLowerCase().includes(pairSearch.toLowerCase());
  });

  const TABS = [
    { id: 'chat',  label: 'Chat Logs',  count: chatMsgs.length },
    { id: 'pairs', label: 'QA Pairs',   count: pairs.length },
  ];

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold text-white">QA Review</h2>
          <p className="text-sm text-white/40 mt-0.5">
            Curate chat turns into published Q&amp;A pairs shown on topic pages
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => tab === 'chat' ? loadChatMessages() : loadQaPairs()}
            className="h-9 px-3 rounded-xl text-xs text-white/60 hover:text-white border border-white/10 hover:border-white/20 flex items-center gap-1.5 transition-colors"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="h-9 px-3 rounded-xl text-xs text-white bg-violet-600 hover:bg-violet-500 flex items-center gap-1.5 transition-colors"
          >
            <Plus size={13} /> New QA Pair
          </button>
        </div>
      </div>

      {/* Create QA form */}
      {showCreate && (
        <div className="rounded-xl p-5 border border-violet-500/25 space-y-4" style={{ background: 'rgba(124,58,237,0.05)' }}>
          <p className="text-sm font-semibold text-white">Create QA Pair</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[['Board slug', newBoard, setNewBoard, 'ahsec'], ['Class slug', newClass, setNewClass, 'class-11'],
              ['Subject slug', newSubject, setNewSubject, 'maths'], ['Topic slug', newTopic, setNewTopic, 'limits']].map(([label, val, setter, ph]) => (
              <div key={label} className="space-y-1">
                <label className="text-[11px] text-white/40 uppercase tracking-wider">{label}</label>
                <input value={val} onChange={(e) => setter(e.target.value)} placeholder={ph}
                  className="w-full h-9 rounded-xl bg-white/5 border border-white/10 text-sm text-white px-3 focus:outline-none focus:border-violet-500" />
              </div>
            ))}
          </div>
          <div className="space-y-1">
            <label className="text-[11px] text-white/40 uppercase tracking-wider">Question</label>
            <input value={newQ} onChange={(e) => setNewQ(e.target.value)}
              placeholder="What is the limit of sin(x)/x as x→0?"
              className="w-full h-9 rounded-xl bg-white/5 border border-white/10 text-sm text-white px-3 focus:outline-none focus:border-violet-500" />
          </div>
          <div className="space-y-1">
            <label className="text-[11px] text-white/40 uppercase tracking-wider">Answer</label>
            <textarea value={newA} onChange={(e) => setNewA(e.target.value)} rows={4}
              placeholder="The limit is 1. This is a fundamental limit in calculus…"
              className="w-full rounded-xl bg-white/5 border border-white/10 text-sm text-white px-3 py-2 focus:outline-none focus:border-violet-500 resize-none" />
          </div>
          <div className="flex gap-2">
            <button onClick={handleCreate} disabled={creating}
              className="h-9 px-5 rounded-xl text-sm font-semibold text-white bg-violet-600 hover:bg-violet-500 flex items-center gap-2 disabled:opacity-50">
              {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Create
            </button>
            <button onClick={() => setShowCreate(false)}
              className="h-9 px-4 rounded-xl text-sm text-white/40 hover:text-white border border-white/10">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-white/8 pb-0">
        {TABS.map(({ id, label, count }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
              tab === id
                ? 'border-violet-500 text-violet-300'
                : 'border-transparent text-white/40 hover:text-white/70'
            }`}
          >
            {label}
            {count > 0 && (
              <span className="ml-1.5 text-[10px] bg-white/10 text-white/40 px-1.5 py-0.5 rounded-full">
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Chat Logs tab ─────────────────────────────────────────────────── */}
      {tab === 'chat' && (
        <div className="space-y-4">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/25" />
            <input
              value={chatSearch} onChange={(e) => setChatSearch(e.target.value)}
              placeholder="Search questions or subjects…"
              className="w-full h-9 pl-9 pr-4 rounded-xl bg-white/5 border border-white/10 text-sm text-white focus:outline-none focus:border-violet-500"
            />
          </div>

          {loading ? (
            <div className="space-y-3">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="rounded-xl p-4 border border-white/6 h-16 animate-pulse" style={{ background: 'rgba(255,255,255,0.02)' }} />
              ))}
            </div>
          ) : filteredChat.length === 0 ? (
            <div className="py-16 text-center">
              <MessageSquare size={28} className="mx-auto text-white/15 mb-3" />
              <p className="text-sm text-white/30">No chat logs yet — start chatting to see logs here</p>
            </div>
          ) : (
            <div className="space-y-2">
              {filteredChat.map((msg) => (
                <div key={msg.id} className="rounded-xl border border-white/8 overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)' }}>
                  <div className="flex items-start gap-3 px-4 py-3">
                    <div className="flex-1 min-w-0">
                      <button onClick={() => toggleChatExpand(msg.id)} className="w-full text-left">
                        <p className="text-sm text-white font-medium truncate">{msg.question}</p>
                        <p className="text-[11px] text-white/30 mt-0.5">
                          {msg.subject_name || 'No subject'} · {msg.board_name || '—'} {msg.class_name || ''} · {new Date(msg.timestamp).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' })}
                        </p>
                      </button>
                    </div>
                    <button
                      onClick={() => handlePromote(msg)}
                      disabled={promoting.has(msg.id)}
                      title="Promote to QA pair"
                      className="shrink-0 h-8 px-3 rounded-xl text-xs text-violet-300 bg-violet-500/10 border border-violet-500/20 flex items-center gap-1.5 hover:bg-violet-500/20 disabled:opacity-50 transition-colors"
                    >
                      {promoting.has(msg.id) ? <Loader2 size={12} className="animate-spin" /> : <ArrowUpCircle size={12} />}
                      Promote
                    </button>
                  </div>
                  {expandedChat.has(msg.id) && (
                    <div className="border-t border-white/6 px-4 py-3 text-xs text-white/40 whitespace-pre-wrap leading-relaxed">
                      {msg.raw_ai_answer}
                    </div>
                  )}
                  <button
                    onClick={() => toggleChatExpand(msg.id)}
                    className="w-full flex justify-center py-1 hover:bg-white/3 transition-colors"
                  >
                    {expandedChat.has(msg.id) ? <ChevronUp size={12} className="text-white/20" /> : <ChevronDown size={12} className="text-white/20" />}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── QA Pairs tab ──────────────────────────────────────────────────── */}
      {tab === 'pairs' && (
        <div className="space-y-4">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/25" />
              <input
                value={pairSearch} onChange={(e) => setPairSearch(e.target.value)}
                placeholder="Search Q&amp;A…"
                className="w-full h-9 pl-9 pr-4 rounded-xl bg-white/5 border border-white/10 text-sm text-white focus:outline-none focus:border-violet-500"
              />
            </div>
            {['all', 'draft', 'published'].map((f) => (
              <button key={f} onClick={() => setPairFilter(f)}
                className={`h-9 px-3 rounded-xl text-xs font-medium border transition-all capitalize ${
                  pairFilter === f ? 'bg-violet-600 border-violet-500 text-white' : 'border-white/12 text-white/40 hover:text-white/70'
                }`}
              >
                {f}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="space-y-3">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="rounded-xl p-4 border border-white/6 h-16 animate-pulse" style={{ background: 'rgba(255,255,255,0.02)' }} />
              ))}
            </div>
          ) : filteredPairs.length === 0 ? (
            <div className="py-16 text-center">
              <BookOpen size={28} className="mx-auto text-white/15 mb-3" />
              <p className="text-sm text-white/30">No QA pairs yet — promote chat logs or create manually</p>
            </div>
          ) : (
            <div className="space-y-2">
              {filteredPairs.map((pair) => (
                <div key={pair.id} className="rounded-xl border border-white/8 overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)' }}>
                  <div className="flex items-start gap-3 px-4 py-3">
                    <div className="flex-1 min-w-0">
                      <button onClick={() => toggleQaExpand(pair.id)} className="w-full text-left">
                        <p className="text-sm text-white font-medium">{pair.question}</p>
                        <div className="flex flex-wrap items-center gap-1.5 mt-1">
                          <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${STATUS_STYLE[pair.status] || STATUS_STYLE.draft}`}>
                            {pair.status}
                          </span>
                          {pair.topic_slug && (
                            <span className="text-[10px] text-white/25">
                              {[pair.board_slug, pair.class_slug, pair.subject_slug, pair.topic_slug].filter(Boolean).join(' / ')}
                            </span>
                          )}
                          {pair.source === 'chat' && (
                            <span className="text-[10px] text-violet-400/60">from chat</span>
                          )}
                        </div>
                      </button>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        onClick={() => handleToggleStatus(pair)}
                        title={pair.status === 'published' ? 'Unpublish' : 'Publish'}
                        className="h-7 w-7 rounded-lg flex items-center justify-center border border-white/10 hover:border-white/20 text-white/40 hover:text-white transition-colors"
                      >
                        {pair.status === 'published' ? <EyeOff size={12} /> : <CheckCircle2 size={12} />}
                      </button>
                      <button
                        onClick={() => handleDelete(pair)}
                        title="Delete"
                        className="h-7 w-7 rounded-lg flex items-center justify-center border border-white/10 hover:border-red-500/30 text-white/40 hover:text-red-400 transition-colors"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>
                  {expandedQa.has(pair.id) && (
                    <div className="border-t border-white/6 px-4 py-3 text-xs text-white/40 whitespace-pre-wrap leading-relaxed">
                      {pair.answer}
                    </div>
                  )}
                  <button
                    onClick={() => toggleQaExpand(pair.id)}
                    className="w-full flex justify-center py-1 hover:bg-white/3 transition-colors"
                  >
                    {expandedQa.has(pair.id) ? <ChevronUp size={12} className="text-white/20" /> : <ChevronDown size={12} className="text-white/20" />}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
