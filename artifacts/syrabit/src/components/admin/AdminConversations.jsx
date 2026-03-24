import { useState, useEffect, useMemo, useRef } from 'react';
import {
  Loader2, MessageSquare, BookOpen, Search, Mail, User,
  ChevronRight, Crown, X, Clock, ArrowLeft,
} from 'lucide-react';
import { adminGetConversations } from '@/utils/api';
import { toast } from 'sonner';
import { formatDistanceToNow, format } from 'date-fns';

const PLAN_COLORS = {
  free: 'text-slate-400 bg-slate-400/10 border-slate-400/20',
  starter: 'text-violet-400 bg-violet-400/10 border-violet-400/20',
  pro: 'text-amber-400 bg-amber-400/10 border-amber-400/20',
};

function UserAvatar({ name, avatar, size = 32 }) {
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

export default function AdminConversations({ adminToken }) {
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [search, setSearch] = useState('');
  const chatEndRef = useRef(null);

  useEffect(() => {
    adminGetConversations(adminToken)
      .then((res) => setConversations(res.data))
      .catch(() => toast.error('Failed to load conversations'))
      .finally(() => setLoading(false));
  }, [adminToken]);

  useEffect(() => {
    if (selected && chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [selected]);

  const totalMessages = useMemo(() => conversations.reduce((sum, c) => sum + (c.messages || []).length, 0), [conversations]);

  const filtered = useMemo(() => {
    if (!search.trim()) return conversations;
    const q = search.toLowerCase();
    return conversations.filter((c) =>
      (c.title || '').toLowerCase().includes(q) ||
      (c.subject_name || '').toLowerCase().includes(q) ||
      (c.user_email || '').toLowerCase().includes(q) ||
      (c.user_name || '').toLowerCase().includes(q)
    );
  }, [conversations, search]);

  const selectedConv = useMemo(() => conversations.find(c => c.id === selected), [conversations, selected]);

  if (loading) return <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-slate-400" /></div>;

  return (
    <div className="flex h-full" style={{ minHeight: 'calc(100vh - 120px)' }}>
      {/* Left: Conversation list */}
      <div className={`${selected ? 'hidden lg:flex' : 'flex'} flex-col w-full lg:w-[380px] lg:min-w-[380px] border-r border-white/[0.06]`}>
        <div className="p-4 border-b border-white/[0.06] space-y-3">
          <div>
            <h2 className="text-slate-200 font-semibold">Conversations ({conversations.length})</h2>
            <p className="text-xs text-slate-500">{totalMessages} total messages</p>
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
          {filtered.map((conv) => (
            <div
              key={conv.id}
              onClick={() => setSelected(conv.id)}
              className={`flex items-start gap-3 p-4 cursor-pointer border-b border-white/[0.04] transition-colors ${
                selected === conv.id ? 'bg-violet-500/10 border-l-2 border-l-violet-500' : 'hover:bg-white/[0.03]'
              }`}
            >
              <UserAvatar name={conv.user_name} avatar={conv.user_avatar} size={36} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium text-slate-200 truncate">{conv.title || 'Untitled'}</p>
                  <span className="text-[10px] text-slate-500 flex-shrink-0">
                    {formatDistanceToNow(new Date(conv.updated_at || conv.created_at), { addSuffix: true })}
                  </span>
                </div>
                <p className="text-xs text-slate-400 truncate">{conv.user_name || 'Unknown'}</p>
                <div className="flex items-center gap-2 mt-1 text-[10px] text-slate-500">
                  {conv.subject_name && <span className="truncate">{conv.subject_name}</span>}
                  <span>{(conv.messages || []).length} msgs</span>
                </div>
              </div>
            </div>
          ))}
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
                <UserAvatar name={selectedConv.user_name} avatar={selectedConv.user_avatar} size={44} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold text-white truncate">{selectedConv.user_name || 'Unknown User'}</h3>
                    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border ${PLAN_COLORS[selectedConv.user_plan] || PLAN_COLORS.free}`}>
                      <Crown size={8} />
                      {(selectedConv.user_plan || 'free').charAt(0).toUpperCase() + (selectedConv.user_plan || 'free').slice(1)}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-slate-500 mt-0.5 flex-wrap">
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
                      <UserAvatar name={selectedConv.user_name} avatar={selectedConv.user_avatar} size={28} />
                    ) : (
                      <div className="w-7 h-7 rounded-lg overflow-hidden flex-shrink-0">
                        <img src="/logo.png" alt="Syra" className="w-full h-full object-cover" />
                      </div>
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-xs font-semibold ${msg.role === 'user' ? 'text-blue-400' : 'text-violet-400'}`}>
                        {msg.role === 'user' ? (selectedConv.user_name || 'Student') : 'Syra AI'}
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
  );
}
