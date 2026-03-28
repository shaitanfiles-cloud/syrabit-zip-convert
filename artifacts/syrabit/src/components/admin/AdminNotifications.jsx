import { useState, useEffect } from 'react';
import { Bell, Send, Clock, Trash2, Users, Loader2, Info, CheckCircle2, AlertTriangle, XCircle, Zap, Plus, ToggleLeft, ToggleRight } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { getNotificationTriggers, createNotificationTrigger, updateNotificationTrigger, deleteNotificationTrigger } from '@/utils/api';

const API_BASE = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

const adminHeaders = (token) => {
  const isRealJwt = token && typeof token === 'string' && token.split('.').length === 3;
  return isRealJwt ? { Authorization: `Bearer ${token}` } : {};
};

const TRIGGER_EVENTS = [
  { id: 'signup',       label: 'User Signed Up' },
  { id: 'inactive_3d',  label: 'Inactive 3 Days' },
  { id: 'inactive_7d',  label: 'Inactive 7 Days' },
  { id: 'plan_upgrade', label: 'Plan Upgraded' },
  { id: 'low_credits',  label: 'Low Credits (< 2)' },
];

const TRIGGER_CHANNELS = [
  { id: 'push',  label: 'Push' },
  { id: 'email', label: 'Email' },
  { id: 'both',  label: 'Both' },
];

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
  const [mainTab, setMainTab]   = useState('broadcast'); // 'broadcast' | 'triggers'
  const [triggers, setTriggers] = useState([]);
  const [trigLoading, setTrigLoading] = useState(false);
  const [newTrig, setNewTrig]   = useState({ name: '', event: 'signup', channel: 'push', message: '', subject: '', enabled: true });

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
    // Load triggers
    getNotificationTriggers(adminToken).then(r => setTriggers(r.data.triggers || [])).catch(() => {});
  }, [adminToken]);

  const handleSaveTrigger = async () => {
    if (!newTrig.name || !newTrig.message) { toast.error('Name and message required'); return; }
    setTrigLoading(true);
    try {
      const r = await createNotificationTrigger(adminToken, newTrig);
      setTriggers(prev => [...prev, r.data]);
      setNewTrig({ name: '', event: 'signup', channel: 'push', message: '', subject: '', enabled: true });
      toast.success('Trigger created!');
    } catch { toast.error('Failed to create trigger'); }
    finally { setTrigLoading(false); }
  };

  const handleToggleTrigger = async (id, enabled) => {
    try {
      await updateNotificationTrigger(adminToken, id, { enabled: !enabled });
      setTriggers(prev => prev.map(t => t.id === id ? { ...t, enabled: !enabled } : t));
    } catch { toast.error('Failed to toggle trigger'); }
  };

  const handleDeleteTrigger = async (id) => {
    try {
      await deleteNotificationTrigger(adminToken, id);
      setTriggers(prev => prev.filter(t => t.id !== id));
      toast.success('Deleted');
    } catch { toast.error('Failed to delete trigger'); }
  };

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
    <div className="space-y-4 max-w-5xl">
      {/* Main tabs */}
      <div style={{ display: 'flex', gap: 4, padding: '4px' }}>
        {[
          { id: 'broadcast', label: '📢 Broadcast' },
          { id: 'triggers',  label: `⚡ Automation Triggers (${triggers.length})` },
        ].map(t => (
          <button key={t.id} onClick={() => setMainTab(t.id)}
            style={{ padding: '6px 16px', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: 'none', background: mainTab === t.id ? '#7c3aed' : 'rgba(255,255,255,0.04)', color: mainTab === t.id ? '#fff' : 'rgba(232,232,232,0.45)' }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Trigger Builder Tab */}
      {mainTab === 'triggers' && (
        <div className="space-y-4">
          {/* New trigger form */}
          <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 16, padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
              <Zap size={15} color="#a78bfa" />
              <span style={{ fontWeight: 700, color: '#e8e8e8', fontSize: 14 }}>Create Automation Trigger</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
              <input value={newTrig.name} onChange={e => setNewTrig(p => ({ ...p, name: e.target.value }))} placeholder="Trigger name (e.g. Welcome Email)"
                style={{ padding: '8px 12px', borderRadius: 8, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.10)', color: '#e8e8e8', fontSize: 13, outline: 'none' }} />
              <input value={newTrig.subject} onChange={e => setNewTrig(p => ({ ...p, subject: e.target.value }))} placeholder="Email subject (optional)"
                style={{ padding: '8px 12px', borderRadius: 8, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.10)', color: '#e8e8e8', fontSize: 13, outline: 'none' }} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
              <select value={newTrig.event} onChange={e => setNewTrig(p => ({ ...p, event: e.target.value }))}
                style={{ padding: '8px 12px', borderRadius: 8, background: '#0f172a', border: '1px solid rgba(255,255,255,0.10)', color: '#e8e8e8', fontSize: 13 }}>
                {TRIGGER_EVENTS.map(e => <option key={e.id} value={e.id}>{e.label}</option>)}
              </select>
              <select value={newTrig.channel} onChange={e => setNewTrig(p => ({ ...p, channel: e.target.value }))}
                style={{ padding: '8px 12px', borderRadius: 8, background: '#0f172a', border: '1px solid rgba(255,255,255,0.10)', color: '#e8e8e8', fontSize: 13 }}>
                {TRIGGER_CHANNELS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </div>
            <textarea value={newTrig.message} onChange={e => setNewTrig(p => ({ ...p, message: e.target.value }))} placeholder="Message body... (use {name} for personalisation)"
              rows={3} style={{ width: '100%', padding: '8px 12px', borderRadius: 8, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.10)', color: '#e8e8e8', fontSize: 13, outline: 'none', resize: 'none', boxSizing: 'border-box' }} />
            <button onClick={handleSaveTrigger} disabled={trigLoading}
              style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 6, padding: '8px 18px', borderRadius: 8, background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)', color: '#fff', fontWeight: 700, fontSize: 13, border: 'none', cursor: 'pointer' }}>
              {trigLoading ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} Save Trigger
            </button>
          </div>

          {/* Existing triggers */}
          {triggers.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 48 }}>
              <Zap size={32} color="rgba(139,92,246,0.2)" style={{ margin: '0 auto 12px' }} />
              <p style={{ color: 'rgba(232,232,232,0.35)', fontSize: 13 }}>No triggers yet — create your first automation above</p>
            </div>
          ) : (
            <div className="space-y-2">
              {triggers.map(t => (
                <div key={t.id} style={{ background: 'rgba(255,255,255,0.02)', border: `1px solid ${t.enabled ? 'rgba(139,92,246,0.20)' : 'rgba(255,255,255,0.06)'}`, borderRadius: 12, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: '#e8e8e8' }}>{t.name}</span>
                      <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 20, background: t.enabled ? 'rgba(16,185,129,0.12)' : 'rgba(100,116,139,0.12)', color: t.enabled ? '#10b981' : '#64748b' }}>
                        {t.enabled ? 'Active' : 'Paused'}
                      </span>
                    </div>
                    <p style={{ fontSize: 11, color: 'rgba(232,232,232,0.4)', marginTop: 2 }}>
                      {TRIGGER_EVENTS.find(e => e.id === t.event)?.label || t.event} → {t.channel} · {t.message?.slice(0, 60)}...
                    </p>
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button onClick={() => handleToggleTrigger(t.id, t.enabled)}
                      style={{ padding: '5px 10px', borderRadius: 7, fontSize: 11, fontWeight: 600, cursor: 'pointer', border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.04)', color: t.enabled ? '#f59e0b' : '#10b981' }}>
                      {t.enabled ? 'Pause' : 'Resume'}
                    </button>
                    <button onClick={() => handleDeleteTrigger(t.id)}
                      style={{ padding: '5px 10px', borderRadius: 7, fontSize: 11, fontWeight: 600, cursor: 'pointer', border: '1px solid rgba(239,68,68,0.2)', background: 'rgba(239,68,68,0.06)', color: '#ef4444' }}>
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Broadcast Tab */}
      {mainTab === 'broadcast' && (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
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
      )}
    </div>
  );
}
