import { useState, useEffect } from 'react';
import { Bell, Send, Clock, Trash2, Users, Loader2, Info, CheckCircle2, AlertTriangle, XCircle, Zap, Plus, ToggleLeft, ToggleRight } from 'lucide-react';
import AdminQuickLinks from './AdminQuickLinks';
import { toast } from 'sonner';
import axios from 'axios';
import { getNotificationTriggers, createNotificationTrigger, updateNotificationTrigger, deleteNotificationTrigger, API_BASE } from '@/utils/api';

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
  { id: 'info',    icon: Info,          color: 'text-blue-600',    bg: 'bg-blue-50',    border: 'border-blue-200'    },
  { id: 'success', icon: CheckCircle2,  color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  { id: 'warning', icon: AlertTriangle, color: 'text-amber-600',   bg: 'bg-amber-50',   border: 'border-amber-200'   },
  { id: 'error',   icon: XCircle,       color: 'text-red-600',     bg: 'bg-red-50',     border: 'border-red-200'     },
];

const AUDIENCES = [
  { id: 'all',     label: 'All Users',    icon: Users },
  { id: 'free',    label: 'Free Plan',    icon: Bell  },
  { id: 'starter', label: 'Starter Plan', icon: Bell  },
  { id: 'pro',     label: 'Pro Plan',     icon: Bell  },
];

export default function AdminNotifications({ adminToken, onNavigate }) {
  const [notifs, setNotifs]     = useState([]);
  const [title, setTitle]       = useState('');
  const [message, setMessage]   = useState('');
  const [type, setType]         = useState('info');
  const [audience, setAudience] = useState('all');
  const [sending, setSending]   = useState(false);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [mainTab, setMainTab]   = useState('broadcast');
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

  const trigInputStyle = { padding: '8px 12px', borderRadius: 8, background: '#f9fafb', border: '1px solid #e5e7eb', color: '#111827', fontSize: 13, outline: 'none' };
  const trigSelectStyle = { padding: '8px 12px', borderRadius: 8, background: '#ffffff', border: '1px solid #e5e7eb', color: '#111827', fontSize: 13 };

  return (
    <div className="space-y-4 max-w-5xl">
      <div style={{ display: 'flex', gap: 4, padding: '4px' }}>
        {[
          { id: 'broadcast', label: '📢 Broadcast' },
          { id: 'triggers',  label: `⚡ Automation Triggers (${triggers.length})` },
        ].map(t => (
          <button key={t.id} onClick={() => setMainTab(t.id)}
            style={{ padding: '6px 16px', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer', border: mainTab === t.id ? '1px solid #c4b5fd' : '1px solid #e5e7eb', background: mainTab === t.id ? '#7c3aed' : '#ffffff', color: mainTab === t.id ? '#fff' : '#6b7280' }}>
            {t.label}
          </button>
        ))}
      </div>

      {mainTab === 'triggers' && (
        <div className="space-y-4">
          <div style={{ background: '#ffffff', border: '1px solid #e5e7eb', borderRadius: 16, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
              <Zap size={15} color="#7c3aed" />
              <span style={{ fontWeight: 700, color: '#111827', fontSize: 14 }}>Create Automation Trigger</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
              <input value={newTrig.name} onChange={e => setNewTrig(p => ({ ...p, name: e.target.value }))} placeholder="Trigger name (e.g. Welcome Email)"
                style={trigInputStyle} />
              <input value={newTrig.subject} onChange={e => setNewTrig(p => ({ ...p, subject: e.target.value }))} placeholder="Email subject (optional)"
                style={trigInputStyle} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
              <select value={newTrig.event} onChange={e => setNewTrig(p => ({ ...p, event: e.target.value }))}
                style={trigSelectStyle}>
                {TRIGGER_EVENTS.map(e => <option key={e.id} value={e.id}>{e.label}</option>)}
              </select>
              <select value={newTrig.channel} onChange={e => setNewTrig(p => ({ ...p, channel: e.target.value }))}
                style={trigSelectStyle}>
                {TRIGGER_CHANNELS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </div>
            <textarea value={newTrig.message} onChange={e => setNewTrig(p => ({ ...p, message: e.target.value }))} placeholder="Message body... (use {name} for personalisation)"
              rows={3} style={{ ...trigInputStyle, width: '100%', resize: 'none', boxSizing: 'border-box' }} />
            <button onClick={handleSaveTrigger} disabled={trigLoading}
              style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 6, padding: '8px 18px', borderRadius: 8, background: '#7c3aed', color: '#fff', fontWeight: 700, fontSize: 13, border: 'none', cursor: 'pointer' }}>
              {trigLoading ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} Save Trigger
            </button>
          </div>

          {triggers.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 48 }}>
              <Zap size={32} color="#d8b4fe" style={{ margin: '0 auto 12px' }} />
              <p style={{ color: '#9ca3af', fontSize: 13 }}>No triggers yet — create your first automation above</p>
            </div>
          ) : (
            <div className="space-y-2">
              {triggers.map(t => (
                <div key={t.id} style={{ background: '#ffffff', border: `1px solid ${t.enabled ? '#e9d5ff' : '#e5e7eb'}`, borderRadius: 12, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12, boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: '#111827' }}>{t.name}</span>
                      <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 20, background: t.enabled ? '#ecfdf5' : '#f3f4f6', color: t.enabled ? '#10b981' : '#6b7280' }}>
                        {t.enabled ? 'Active' : 'Paused'}
                      </span>
                    </div>
                    <p style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>
                      {TRIGGER_EVENTS.find(e => e.id === t.event)?.label || t.event} → {t.channel} · {t.message?.slice(0, 60)}...
                    </p>
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button onClick={() => handleToggleTrigger(t.id, t.enabled)}
                      style={{ padding: '5px 10px', borderRadius: 7, fontSize: 11, fontWeight: 600, cursor: 'pointer', border: '1px solid #e5e7eb', background: '#ffffff', color: t.enabled ? '#f59e0b' : '#10b981' }}>
                      {t.enabled ? 'Pause' : 'Resume'}
                    </button>
                    <button onClick={() => handleDeleteTrigger(t.id)}
                      style={{ padding: '5px 10px', borderRadius: 7, fontSize: 11, fontWeight: 600, cursor: 'pointer', border: '1px solid #fecaca', background: '#fef2f2', color: '#ef4444' }}>
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {mainTab === 'broadcast' && (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <div className="lg:col-span-7 rounded-2xl border border-gray-200 p-5 space-y-4 bg-white shadow-sm">
        <h2 className="text-base font-bold text-gray-900">Compose Notification</h2>

        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Notification title"
          className="w-full h-9 px-3 rounded-xl text-sm text-gray-900 outline-none bg-gray-50 border border-gray-200 focus:border-violet-400 focus:ring-2 focus:ring-violet-500/20"
        />
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Message body..."
          rows={4}
          className="w-full p-3 rounded-xl text-sm text-gray-900 resize-none outline-none bg-gray-50 border border-gray-200 focus:border-violet-400 focus:ring-2 focus:ring-violet-500/20"
        />

        <div>
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-2">Type</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {NOTIF_TYPES.map(({ id, icon: Icon, color, bg, border }) => (
              <button
                key={id}
                onClick={() => setType(id)}
                className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
                  type === id ? `${bg} ${border} ${color}` : 'border-gray-200 text-gray-500'
                }`}
              >
                <Icon size={12} /> {id.charAt(0).toUpperCase() + id.slice(1)}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-2">Audience</p>
          <div className="space-y-1.5">
            {AUDIENCES.map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setAudience(id)}
                className={`w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-all border ${
                  audience === id
                    ? 'border-violet-200 bg-violet-50 text-violet-700'
                    : 'border-gray-200 text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                }`}
              >
                <div className={`w-3 h-3 rounded-full border ${audience === id ? 'border-violet-500 bg-violet-500' : 'border-gray-300'}`} />
                {label}
              </button>
            ))}
          </div>
        </div>

        {title && (
          <div className={`p-3 rounded-xl border ${currentType.bg} ${currentType.border}`}>
            <div className="flex items-center gap-2 mb-1">
              <TypeIcon size={14} className={currentType.color} />
              <span className="text-sm font-medium text-gray-900">{title}</span>
            </div>
            <p className="text-xs text-gray-500">{message}</p>
          </div>
        )}

        <div className="flex gap-2">
          <button
            onClick={() => handleSend('draft')}
            disabled={sending}
            className="flex-1 h-9 rounded-xl text-xs font-medium text-gray-600 border border-gray-200 hover:bg-gray-50"
          >
            <Clock size={12} className="inline mr-1" /> Save Draft
          </button>
          <button
            onClick={() => handleSend('sent')}
            disabled={sending}
            className="flex-1 h-9 rounded-xl text-xs font-semibold text-white flex items-center justify-center gap-1.5 bg-violet-600 hover:bg-violet-700 transition-colors"
          >
            {sending ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />} Send Now
          </button>
        </div>
      </div>

      <div className="lg:col-span-5 rounded-2xl border border-gray-200 overflow-hidden bg-white shadow-sm">
        <div className="p-4 border-b border-gray-100 flex items-center justify-between">
          <p className="text-sm font-bold text-gray-900">Notifications</p>
          <div className="flex gap-1.5 text-[10px]">
            <span className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">{notifs.length} total</span>
            <span className="px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-600">
              {notifs.filter((n) => n.status === 'sent').length} sent
            </span>
          </div>
        </div>

        <div className="overflow-y-auto" style={{ maxHeight: 480 }}>
          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 size={20} className="animate-spin text-gray-300" />
            </div>
          ) : error ? (
            <div className="p-4 text-center text-sm text-red-500">{error}</div>
          ) : notifs.length === 0 ? (
            <div className="text-center py-12 space-y-2">
              <Bell size={28} className="mx-auto text-gray-200" />
              <p className="text-sm text-gray-400">No notifications yet</p>
              <p className="text-xs text-gray-300">Compose and send your first notification</p>
            </div>
          ) : notifs.map((n) => {
            const tc = NOTIF_TYPES.find((t) => t.id === n.type) || NOTIF_TYPES[0];
            const Icon = tc.icon;
            return (
              <div
                key={n.id}
                className={`p-3 border-b border-gray-100 ${n.status === 'draft' ? 'border-l-2 border-l-amber-400' : ''} group`}
              >
                <div className="flex items-start gap-2.5">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${tc.bg}`}>
                    <Icon size={14} className={tc.color} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="text-xs font-medium text-gray-900">{n.title}</span>
                      <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${
                        n.status === 'sent' ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'
                      }`}>
                        {n.status}
                      </span>
                    </div>
                    <p className="text-[11px] text-gray-500 truncate">{n.message}</p>
                    <p className="text-[10px] text-gray-400 mt-0.5">→ {n.audience}</p>
                  </div>
                  <button
                    onClick={() => handleDelete(n.id)}
                    className="opacity-0 group-hover:opacity-100 p-1 text-gray-300 hover:text-red-500 transition-all"
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
      <AdminQuickLinks links={['users','conversations','settings','activitylog']} onNavigate={onNavigate} />
    </div>
  );
}
