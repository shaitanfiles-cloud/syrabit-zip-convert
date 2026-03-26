import { useState, useEffect } from 'react';
import { Bell, Send, Clock, Trash2, Users, Loader2, Info, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';

const API_BASE = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

const adminHeaders = (token) => {
  const isRealJwt = token && typeof token === 'string' && token.split('.').length === 3;
  return isRealJwt ? { Authorization: `Bearer ${token}` } : {};
};

const NOTIF_TYPES = [
  { id: 'info',    icon: Info,          color: 'text-blue-400',    bg: 'bg-blue-500/10',    border: 'border-blue-500/25'    },
  { id: 'success', icon: CheckCircle2,  color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/25' },
  { id: 'warning', icon: AlertTriangle, color: 'text-amber-400',   bg: 'bg-amber-500/10',   border: 'border-amber-500/25'   },
  { id: 'error',   icon: XCircle,       color: 'text-red-400',     bg: 'bg-red-500/10',     border: 'border-red-500/25'     },
];

const AUDIENCES = [
  { id: 'all',     label: 'All Users',    icon: Users },
  { id: 'free',    label: 'Free Plan',    icon: Bell  },
  { id: 'starter', label: 'Starter Plan', icon: Bell  },
  { id: 'pro',     label: 'Pro Plan',     icon: Bell  },
];

export default function AdminNotifications({ adminToken }) {
  const [notifs, setNotifs]     = useState([]);
  const [title, setTitle]       = useState('');
  const [message, setMessage]   = useState('');
  const [type, setType]         = useState('info');
  const [audience, setAudience] = useState('all');
  const [sending, setSending]   = useState(false);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);

  useEffect(() => {
    axios.get(`${API_BASE}/admin/notifications`, {
      headers: adminHeaders(adminToken),
      withCredentials: true
    })
      .then((r) => {
        const data = r.data;
        const arr = Array.isArray(data) ? data : (data?.notifications || data?.items || []);
        setNotifs(arr);
      })
      .catch(() => {
        setError('Failed to load notifications');
        setNotifs([]);
      })
      .finally(() => setLoading(false));
  }, [adminToken]);

  const handleSend = async (status) => {
    if (!title.trim() || !message.trim()) { toast.error('Title and message required'); return; }
    setSending(true);
    try {
      const res = await axios.post(
        `${API_BASE}/admin/notifications`,
        { title, message, type, audience, status },
        { headers: adminHeaders(adminToken), withCredentials: true }
      );
      setNotifs((n) => [res.data, ...n]);
      setTitle(''); setMessage('');
      toast.success(status === 'sent' ? 'Notification sent!' : 'Draft saved');
    } catch { toast.error('Failed to send notification'); }
    finally { setSending(false); }
  };

  const handleDelete = async (id) => {
    try {
      await axios.delete(`${API_BASE}/admin/notifications/${id}`, {
        headers: adminHeaders(adminToken),
        withCredentials: true
      });
      setNotifs((n) => n.filter((x) => x.id !== id));
      toast.success('Deleted');
    } catch { toast.error('Failed to delete'); }
  };

  const currentType = NOTIF_TYPES.find((t) => t.id === type) || NOTIF_TYPES[0];
  const TypeIcon = currentType.icon;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 max-w-5xl">
      {/* Compose */}
      <div className="lg:col-span-7 rounded-2xl border border-white/6 p-5 space-y-4" style={{ background: 'rgba(255,255,255,0.02)' }}>
        <h2 className="text-base font-bold text-white">Compose Notification</h2>

        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Notification title"
          className="w-full h-9 px-3 rounded-xl text-sm text-white outline-none"
          style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.10)' }}
        />
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Message body..."
          rows={4}
          className="w-full p-3 rounded-xl text-sm text-white resize-none outline-none"
          style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.10)' }}
        />

        {/* Type */}
        <div>
          <p className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-2">Type</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {NOTIF_TYPES.map(({ id, icon: Icon, color, bg, border }) => (
              <button
                key={id}
                onClick={() => setType(id)}
                className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
                  type === id ? `${bg} ${border} ${color}` : 'border-white/8 text-white/40'
                }`}
              >
                <Icon size={12} /> {id.charAt(0).toUpperCase() + id.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Audience */}
        <div>
          <p className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-2">Audience</p>
          <div className="space-y-1.5">
            {AUDIENCES.map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setAudience(id)}
                className={`w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-all border ${
                  audience === id
                    ? 'border-violet-500/30 bg-violet-500/10 text-violet-300'
                    : 'border-white/6 text-white/40 hover:text-white/60 hover:bg-white/3'
                }`}
              >
                <div className={`w-3 h-3 rounded-full border ${audience === id ? 'border-violet-400 bg-violet-400' : 'border-white/20'}`} />
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Preview */}
        {title && (
          <div className={`p-3 rounded-xl border ${currentType.bg} ${currentType.border}`}>
            <div className="flex items-center gap-2 mb-1">
              <TypeIcon size={14} className={currentType.color} />
              <span className="text-sm font-medium text-white">{title}</span>
            </div>
            <p className="text-xs text-white/60">{message}</p>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2">
          <button
            onClick={() => handleSend('draft')}
            disabled={sending}
            className="flex-1 h-9 rounded-xl text-xs font-medium text-white/60 border border-white/10 hover:bg-white/5"
          >
            <Clock size={12} className="inline mr-1" /> Save Draft
          </button>
          <button
            onClick={() => handleSend('sent')}
            disabled={sending}
            className="flex-1 h-9 rounded-xl text-xs font-semibold text-white flex items-center justify-center gap-1.5"
            style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)' }}
          >
            {sending ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />} Send Now
          </button>
        </div>
      </div>

      {/* List */}
      <div className="lg:col-span-5 rounded-2xl border border-white/6 overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)' }}>
        <div className="p-4 border-b border-white/6 flex items-center justify-between">
          <p className="text-sm font-bold text-white">Notifications</p>
          <div className="flex gap-1.5 text-[10px]">
            <span className="px-2 py-0.5 rounded-full bg-white/5 text-white/40">{notifs.length} total</span>
            <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400">
              {notifs.filter((n) => n.status === 'sent').length} sent
            </span>
          </div>
        </div>

        <div className="overflow-y-auto" style={{ maxHeight: 480 }}>
          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 size={20} className="animate-spin text-white/20" />
            </div>
          ) : error ? (
            <div className="p-4 text-center text-sm text-red-400/70">{error}</div>
          ) : notifs.length === 0 ? (
            <div className="text-center py-12 space-y-2">
              <Bell size={28} className="mx-auto text-white/10" />
              <p className="text-sm text-white/20">No notifications yet</p>
              <p className="text-xs text-white/10">Compose and send your first notification</p>
            </div>
          ) : notifs.map((n) => {
            const tc = NOTIF_TYPES.find((t) => t.id === n.type) || NOTIF_TYPES[0];
            const Icon = tc.icon;
            return (
              <div
                key={n.id}
                className={`p-3 border-b border-white/5 ${n.status === 'draft' ? 'border-l-2 border-l-amber-500/40' : ''} group`}
              >
                <div className="flex items-start gap-2.5">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${tc.bg}`}>
                    <Icon size={14} className={tc.color} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="text-xs font-medium text-white">{n.title}</span>
                      <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${
                        n.status === 'sent' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-amber-500/10 text-amber-400'
                      }`}>
                        {n.status}
                      </span>
                    </div>
                    <p className="text-[11px] text-white/50 truncate">{n.message}</p>
                    <p className="text-[10px] text-white/25 mt-0.5">→ {n.audience}</p>
                  </div>
                  <button
                    onClick={() => handleDelete(n.id)}
                    className="opacity-0 group-hover:opacity-100 p-1 text-white/30 hover:text-red-400 transition-all"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
