import { useState, useEffect, useCallback } from 'react';
import {
  Shield, Bot, AlertTriangle, RefreshCw, Loader2,
  Hash, Globe, Clock, TrendingUp, Eye, Ban, Unlock,
  Settings, Bell, Mail, Link2, Save, Check, RotateCcw,
  Calendar, Filter, CheckCheck, History,
} from 'lucide-react';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts';
import { adminGetSpoofedBots, adminGetBlockedIps, adminBlockIp, adminUnblockIp, adminGetAlertSettings, adminUpdateAlertSettings, adminGetTtlMonitor, adminGetAlerts, adminAcknowledgeAlert, adminAcknowledgeAllAlerts } from '@/utils/api';
import { Database, Activity, CheckCircle2, XCircle } from 'lucide-react';

function GlassCard({ children, className = '' }) {
  return (
    <div className={`relative rounded-2xl overflow-hidden bg-white border border-gray-200 shadow-sm ${className}`}>
      <div className="relative">{children}</div>
    </div>
  );
}

function StatCard({ label, value, icon: Icon, color, pulse }) {
  return (
    <div className="relative rounded-2xl p-5 overflow-hidden bg-white border border-gray-200 shadow-sm">
      {pulse && (
        <span className="absolute top-3 right-3 flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: color }} />
          <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: color }} />
        </span>
      )}
      <div className="flex items-center justify-between mb-3">
        <p className="text-gray-500 text-xs font-medium tracking-wide uppercase">{label}</p>
        <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: `${color}15` }}>
          <Icon size={16} style={{ color }} />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900 tracking-tight">
        {typeof value === 'number' ? value.toLocaleString() : (value ?? '—')}
      </p>
    </div>
  );
}

function AlertThresholdPanel({ adminToken }) {
  const [settings, setSettings] = useState(null);
  const [form, setForm] = useState({ spoof_rpm: 50, auto_block_threshold: 100, auto_block_expiry_hours: 168, email: '', webhook_url: '' });
  const [defaults, setDefaults] = useState(null);
  const [loadingSettings, setLoadingSettings] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [settingsError, setSettingsError] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await adminGetAlertSettings(adminToken);
        const d = res.data;
        setSettings(d);
        setDefaults(d.defaults);
        setForm({
          spoof_rpm: d.thresholds?.spoof_rpm ?? d.defaults?.thresholds?.spoof_rpm ?? 50,
          auto_block_threshold: d.thresholds?.auto_block_threshold ?? d.defaults?.thresholds?.auto_block_threshold ?? 100,
          auto_block_expiry_hours: d.thresholds?.auto_block_expiry_hours ?? d.defaults?.thresholds?.auto_block_expiry_hours ?? 168,
          email: d.notification_channels?.email ?? '',
          webhook_url: d.notification_channels?.webhook_url ?? '',
        });
      } catch {
        setSettingsError('Failed to load alert settings');
      } finally {
        setLoadingSettings(false);
      }
    })();
  }, [adminToken]);

  const validateField = (field, value) => {
    if (field === 'spoof_rpm') {
      const num = Number(value);
      if (isNaN(num) || !num) return 'RPM threshold is required';
      if (num <= 0) return 'Must be a positive number';
      if (num > 10000) return 'Maximum allowed value is 10,000';
      if (!Number.isInteger(num)) return 'Must be a whole number';
      return null;
    }
    if (field === 'auto_block_threshold') {
      const num = Number(value);
      if (isNaN(num)) return 'Auto-block threshold is required';
      if (num < 0) return 'Must be zero or positive (0 = disabled)';
      if (num > 100000) return 'Maximum allowed value is 100,000';
      if (!Number.isInteger(num)) return 'Must be a whole number';
      return null;
    }
    if (field === 'auto_block_expiry_hours') {
      const num = Number(value);
      if (isNaN(num)) return 'Expiry hours is required';
      if (num < 0) return 'Must be zero or positive (0 = permanent)';
      if (num > 8760) return 'Maximum allowed is 8,760 hours (1 year)';
      return null;
    }
    if (field === 'email') {
      if (!value) return null;
      if (!value.includes('@') || !value.includes('.')) return 'Enter a valid email (e.g. admin@example.com)';
      return null;
    }
    if (field === 'webhook_url') {
      if (!value) return null;
      if (!value.startsWith('http://') && !value.startsWith('https://')) return 'Must start with http:// or https://';
      try { new URL(value); } catch { return 'Enter a valid URL'; }
      return null;
    }
    return null;
  };

  const handleFieldChange = (field, value) => {
    setForm(prev => ({ ...prev, [field]: value }));
    const err = validateField(field, value);
    setFieldErrors(prev => ({ ...prev, [field]: err }));
    if (settingsError) setSettingsError(null);
  };

  const parseBackendError = (err) => {
    const resp = err.response;
    if (!resp) return { general: 'Network error — could not reach server' };
    const detail = resp.data?.detail;
    if (resp.status === 422 && Array.isArray(detail)) {
      const errors = {};
      for (const item of detail) {
        const loc = item.loc || [];
        const field = loc[loc.length - 1] || 'general';
        const mapped = field === 'spoof_rpm' ? 'spoof_rpm'
          : field === 'auto_block_threshold' ? 'auto_block_threshold'
          : field === 'email' ? 'email'
          : field === 'webhook_url' ? 'webhook_url'
          : null;
        if (mapped) {
          errors[mapped] = item.msg || 'Invalid value';
        } else {
          errors.general = item.msg || 'Validation error';
        }
      }
      return Object.keys(errors).length ? errors : { general: 'Validation failed' };
    }
    if (typeof detail === 'string') {
      const lower = detail.toLowerCase();
      if (lower.includes('expiry')) return { auto_block_expiry_hours: detail };
      if (lower.includes('auto_block')) return { auto_block_threshold: detail };
      if (lower.includes('threshold') || lower.includes('rpm') || lower.includes('spoof_rpm')) return { spoof_rpm: detail };
      if (lower.includes('email')) return { email: detail };
      if (lower.includes('webhook')) return { webhook_url: detail };
      return { general: detail };
    }
    return { general: detail || `Server error (${resp.status})` };
  };

  const handleSave = async () => {
    const errors = {};
    errors.spoof_rpm = validateField('spoof_rpm', form.spoof_rpm);
    errors.auto_block_threshold = validateField('auto_block_threshold', form.auto_block_threshold);
    errors.auto_block_expiry_hours = validateField('auto_block_expiry_hours', form.auto_block_expiry_hours);
    errors.email = validateField('email', form.email);
    errors.webhook_url = validateField('webhook_url', form.webhook_url);
    const cleaned = {};
    for (const [k, v] of Object.entries(errors)) { if (v) cleaned[k] = v; }
    setFieldErrors(cleaned);
    if (Object.keys(cleaned).length) {
      setSettingsError(null);
      setSaving(false);
      return;
    }
    setSaving(true);
    setSettingsError(null);
    setSaved(false);
    try {
      await adminUpdateAlertSettings(adminToken, {
        thresholds: {
          ...settings?.thresholds,
          spoof_rpm: Number(form.spoof_rpm),
          auto_block_threshold: Number(form.auto_block_threshold),
          auto_block_expiry_hours: Number(form.auto_block_expiry_hours),
        },
        expiration: settings?.expiration || {},
        notification_channels: {
          email: form.email.trim(),
          webhook_url: form.webhook_url.trim(),
        },
      });
      setFieldErrors({});
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      const parsed = parseBackendError(err);
      const { general, ...fields } = parsed;
      if (Object.keys(fields).length) setFieldErrors(prev => ({ ...prev, ...fields }));
      if (general) setSettingsError(general);
      else if (!Object.keys(fields).length) setSettingsError('Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    if (defaults) {
      setForm({
        spoof_rpm: defaults.thresholds?.spoof_rpm ?? 50,
        auto_block_threshold: defaults.thresholds?.auto_block_threshold ?? 100,
        auto_block_expiry_hours: defaults.thresholds?.auto_block_expiry_hours ?? 168,
        email: defaults.notification_channels?.email ?? '',
        webhook_url: defaults.notification_channels?.webhook_url ?? '',
      });
      setFieldErrors({});
      setSettingsError(null);
    }
  };

  const hasErrors = Object.values(fieldErrors).some(Boolean);

  if (loadingSettings) {
    return (
      <GlassCard>
        <div className="p-5 flex items-center gap-2 text-sm text-gray-400">
          <Loader2 size={14} className="animate-spin" />
          Loading alert settings...
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-5 flex items-center justify-between hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-amber-50">
            <Bell size={16} className="text-amber-500" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-gray-900">Alert Threshold Controls</h3>
            <p className="text-[10px] text-gray-400 mt-0.5">
              RPM threshold: {form.spoof_rpm} &middot; Auto-block: {Number(form.auto_block_threshold) > 0 ? `${form.auto_block_threshold}/24h` : 'disabled'} &middot; Expiry: {Number(form.auto_block_expiry_hours) > 0 ? `${Math.round(Number(form.auto_block_expiry_hours) / 24)}d` : 'permanent'} &middot; Notifications: {form.email || form.webhook_url ? 'configured' : 'not configured'}
            </p>
          </div>
        </div>
        <Settings size={14} className={`text-gray-400 transition-transform ${expanded ? 'rotate-90' : ''}`} />
      </button>

      {expanded && (
        <div className="border-t border-gray-100 p-5 space-y-5">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">
              Spoof RPM Alert Threshold
            </label>
            <p className="text-[10px] text-gray-400 mb-2">
              An alert fires when spoofed bot requests per minute exceed this value (default: {defaults?.thresholds?.spoof_rpm ?? 50})
            </p>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min="1"
                max="10000"
                value={form.spoof_rpm}
                onChange={(e) => handleFieldChange('spoof_rpm', e.target.value)}
                className={`w-32 text-sm border rounded-lg px-3 py-2 bg-white text-gray-900 focus:outline-none focus:ring-2 ${
                  fieldErrors.spoof_rpm
                    ? 'border-red-300 focus:ring-red-200 focus:border-red-300'
                    : 'border-gray-200 focus:ring-violet-200 focus:border-violet-300'
                }`}
              />
              <span className="text-xs text-gray-400">requests/min</span>
            </div>
            {fieldErrors.spoof_rpm && (
              <p className="text-[11px] text-red-500 mt-1">{fieldErrors.spoof_rpm}</p>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">
              Auto-Block Threshold (24h)
            </label>
            <p className="text-[10px] text-gray-400 mb-2">
              IPs exceeding this many spoofing attempts in 24 hours are automatically blocked. Set to 0 to disable auto-blocking (default: {defaults?.thresholds?.auto_block_threshold ?? 100})
            </p>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min="0"
                max="100000"
                value={form.auto_block_threshold}
                onChange={(e) => handleFieldChange('auto_block_threshold', e.target.value)}
                className={`w-32 text-sm border rounded-lg px-3 py-2 bg-white text-gray-900 focus:outline-none focus:ring-2 ${
                  fieldErrors.auto_block_threshold
                    ? 'border-red-300 focus:ring-red-200 focus:border-red-300'
                    : 'border-gray-200 focus:ring-violet-200 focus:border-violet-300'
                }`}
              />
              <span className="text-xs text-gray-400">attempts/24h</span>
            </div>
            {fieldErrors.auto_block_threshold && (
              <p className="text-[11px] text-red-500 mt-1">{fieldErrors.auto_block_threshold}</p>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1.5">
              Auto-Block Expiry
            </label>
            <p className="text-[10px] text-gray-400 mb-2">
              Auto-blocked IPs are automatically unblocked after this many hours. Set to 0 for permanent blocks (default: {defaults?.thresholds?.auto_block_expiry_hours ?? 168}h = {Math.round((defaults?.thresholds?.auto_block_expiry_hours ?? 168) / 24)}d)
            </p>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min="0"
                max="8760"
                value={form.auto_block_expiry_hours}
                onChange={(e) => handleFieldChange('auto_block_expiry_hours', e.target.value)}
                className={`w-32 text-sm border rounded-lg px-3 py-2 bg-white text-gray-900 focus:outline-none focus:ring-2 ${
                  fieldErrors.auto_block_expiry_hours
                    ? 'border-red-300 focus:ring-red-200 focus:border-red-300'
                    : 'border-gray-200 focus:ring-violet-200 focus:border-violet-300'
                }`}
              />
              <span className="text-xs text-gray-400">hours {Number(form.auto_block_expiry_hours) > 0 ? `(${Math.round(Number(form.auto_block_expiry_hours) / 24)}d)` : '(permanent)'}</span>
            </div>
            {fieldErrors.auto_block_expiry_hours && (
              <p className="text-[11px] text-red-500 mt-1">{fieldErrors.auto_block_expiry_hours}</p>
            )}
          </div>

          <div className="border-t border-gray-100 pt-5">
            <h4 className="text-xs font-medium text-gray-700 mb-3 flex items-center gap-1.5">
              <Bell size={12} className="text-gray-400" />
              Notification Channels
            </h4>
            <div className="space-y-4">
              <div>
                <label className="block text-[11px] font-medium text-gray-600 mb-1 flex items-center gap-1.5">
                  <Mail size={11} className="text-gray-400" />
                  Alert Email
                </label>
                <input
                  type="email"
                  placeholder="admin@example.com"
                  value={form.email}
                  onChange={(e) => handleFieldChange('email', e.target.value)}
                  className={`w-full text-sm border rounded-lg px-3 py-2 bg-white text-gray-900 placeholder-gray-300 focus:outline-none focus:ring-2 ${
                    fieldErrors.email
                      ? 'border-red-300 focus:ring-red-200 focus:border-red-300'
                      : 'border-gray-200 focus:ring-violet-200 focus:border-violet-300'
                  }`}
                />
                {fieldErrors.email ? (
                  <p className="text-[11px] text-red-500 mt-1">{fieldErrors.email}</p>
                ) : (
                  <p className="text-[10px] text-gray-400 mt-1">
                    Receives email alerts via Resend when thresholds are exceeded
                  </p>
                )}
              </div>
              <div>
                <label className="block text-[11px] font-medium text-gray-600 mb-1 flex items-center gap-1.5">
                  <Link2 size={11} className="text-gray-400" />
                  Webhook URL
                </label>
                <input
                  type="url"
                  placeholder="https://hooks.slack.com/services/..."
                  value={form.webhook_url}
                  onChange={(e) => handleFieldChange('webhook_url', e.target.value)}
                  className={`w-full text-sm border rounded-lg px-3 py-2 bg-white text-gray-900 placeholder-gray-300 focus:outline-none focus:ring-2 ${
                    fieldErrors.webhook_url
                      ? 'border-red-300 focus:ring-red-200 focus:border-red-300'
                      : 'border-gray-200 focus:ring-violet-200 focus:border-violet-300'
                  }`}
                />
                {fieldErrors.webhook_url ? (
                  <p className="text-[11px] text-red-500 mt-1">{fieldErrors.webhook_url}</p>
                ) : (
                  <p className="text-[10px] text-gray-400 mt-1">
                    Slack, Discord, or generic webhook endpoint for alert notifications
                  </p>
                )}
              </div>
            </div>
          </div>

          {settingsError && (
            <div className="flex items-center gap-2 text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">
              <AlertTriangle size={12} />
              {settingsError}
            </div>
          )}

          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={handleSave}
              disabled={saving || hasErrors}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium bg-violet-600 text-white hover:bg-violet-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : saved ? <Check size={12} /> : <Save size={12} />}
              {saving ? 'Saving...' : saved ? 'Saved' : 'Save Changes'}
            </button>
            <button
              onClick={handleReset}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium text-gray-500 hover:bg-gray-100 transition-colors"
            >
              <RotateCcw size={12} />
              Reset to Defaults
            </button>
          </div>
        </div>
      )}
    </GlassCard>
  );
}

function TtlMonitorPanel({ adminToken }) {
  const [ttlData, setTtlData] = useState(null);
  const [ttlLoading, setTtlLoading] = useState(true);
  const [ttlError, setTtlError] = useState(null);
  const [expanded, setExpanded] = useState(false);

  const fetchTtl = useCallback(async () => {
    setTtlLoading(true);
    setTtlError(null);
    try {
      const res = await adminGetTtlMonitor(adminToken);
      setTtlData(res.data);
    } catch (err) {
      setTtlError(err.response?.data?.detail || 'Failed to load TTL monitoring data');
    } finally {
      setTtlLoading(false);
    }
  }, [adminToken]);

  useEffect(() => { fetchTtl(); }, [fetchTtl]);

  const healthColor = ttlData?.health_status === 'healthy' ? '#10b981' : '#f59e0b';
  const HealthIcon = ttlData?.health_status === 'healthy' ? CheckCircle2 : AlertTriangle;

  if (ttlLoading && !ttlData) {
    return (
      <GlassCard>
        <div className="p-5 flex items-center gap-2 text-sm text-gray-400">
          <Loader2 size={14} className="animate-spin" />
          Loading TTL monitoring data...
        </div>
      </GlassCard>
    );
  }

  if (ttlError && !ttlData) {
    return (
      <GlassCard className="p-6">
        <div className="flex items-center gap-3 text-red-500">
          <XCircle size={18} />
          <p className="text-sm">{ttlError}</p>
        </div>
        <button onClick={fetchTtl} className="mt-3 text-sm text-violet-600 hover:text-violet-800 flex items-center gap-1.5">
          <RefreshCw size={13} /> Retry
        </button>
      </GlassCard>
    );
  }

  if (!ttlData) return null;

  const ageDist = ttlData.age_distribution || [];
  const dailyIngest = ttlData.daily_ingest || [];

  return (
    <GlassCard>
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(!expanded); } }}
        className="w-full p-5 flex items-center justify-between hover:bg-gray-50 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-teal-50">
            <Database size={16} className="text-teal-500" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-gray-900">TTL Cleanup Monitor</h3>
            <p className="text-[10px] text-gray-400 mt-0.5">
              {ttlData.total_documents?.toLocaleString()} docs &middot; TTL: {ttlData.ttl_index?.ttl_days || 90} days &middot;
              <span style={{ color: healthColor }} className="font-medium ml-1">
                {ttlData.health_status === 'healthy' ? 'Healthy' : 'Needs attention'}
              </span>
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); fetchTtl(); }}
            disabled={ttlLoading}
            className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <RefreshCw size={12} className={`text-gray-400 ${ttlLoading ? 'animate-spin' : ''}`} />
          </button>
          <Activity size={14} className={`text-gray-400 transition-transform ${expanded ? 'rotate-90' : ''}`} />
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-100 p-5 space-y-5">
          <div className="flex items-start gap-3 p-3 rounded-xl" style={{ background: `${healthColor}08`, border: `1px solid ${healthColor}20` }}>
            <HealthIcon size={16} style={{ color: healthColor }} className="mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-xs font-medium" style={{ color: healthColor }}>
                {ttlData.health_status === 'healthy' ? 'TTL Cleanup Healthy' : 'TTL Cleanup Warning'}
              </p>
              <p className="text-[11px] text-gray-500 mt-0.5">{ttlData.health_message}</p>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-xl border border-gray-100 p-3 bg-gray-50">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider">Total Documents</p>
              <p className="text-lg font-bold text-gray-900 mt-1">{ttlData.total_documents?.toLocaleString()}</p>
            </div>
            <div className="rounded-xl border border-gray-100 p-3 bg-gray-50">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider">TTL Duration</p>
              <p className="text-lg font-bold text-gray-900 mt-1">{ttlData.ttl_index?.ttl_days || 90}d</p>
            </div>
            <div className="rounded-xl border border-gray-100 p-3 bg-gray-50">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider">TTL Index</p>
              <p className="text-lg font-bold text-gray-900 mt-1">{ttlData.ttl_index?.name ? 'Active' : 'Missing'}</p>
            </div>
            <div className="rounded-xl border border-gray-100 p-3 bg-gray-50">
              <p className="text-[10px] text-gray-400 uppercase tracking-wider">String Timestamps</p>
              <p className={`text-lg font-bold mt-1 ${ttlData.string_timestamps_remaining > 0 ? 'text-amber-600' : 'text-gray-900'}`}>
                {ttlData.string_timestamps_remaining?.toLocaleString()}
              </p>
            </div>
          </div>

          {ageDist.length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-gray-700 mb-3">Document Age Distribution</h4>
              <div className="space-y-2">
                {ageDist.map((bucket) => {
                  const maxCount = Math.max(...ageDist.map(b => b.count), 1);
                  const pct = (bucket.count / maxCount) * 100;
                  const isOverTtl = bucket.label.includes('past TTL');
                  return (
                    <div key={bucket.label} className="flex items-center gap-3">
                      <span className={`text-[11px] w-32 text-right flex-shrink-0 ${isOverTtl && bucket.count > 0 ? 'text-amber-600 font-medium' : 'text-gray-500'}`}>{bucket.label}</span>
                      <div className="flex-1 h-6 bg-gray-50 rounded-lg overflow-hidden border border-gray-100">
                        <div
                          className="h-full rounded-lg transition-all duration-500"
                          style={{
                            width: `${Math.max(pct, bucket.count > 0 ? 2 : 0)}%`,
                            background: isOverTtl && bucket.count > 0 ? '#f59e0b' : '#8b5cf6',
                          }}
                        />
                      </div>
                      <span className={`text-[11px] font-medium w-14 text-right flex-shrink-0 ${isOverTtl && bucket.count > 0 ? 'text-amber-600' : 'text-gray-600'}`}>
                        {bucket.count.toLocaleString()}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {dailyIngest.length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-gray-700 mb-2">Daily Document Ingest (Last 30 Days)</h4>
              <div style={{ height: 200 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={dailyIngest}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 10, fill: '#94a3b8' }}
                      tickFormatter={(v) => {
                        const d = new Date(v);
                        return `${d.getMonth() + 1}/${d.getDate()}`;
                      }}
                    />
                    <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} allowDecimals={false} />
                    <Tooltip
                      contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}
                      labelFormatter={(v) => new Date(v).toLocaleDateString()}
                    />
                    <Bar dataKey="count" fill="#14b8a6" radius={[4, 4, 0, 0]} name="Documents Added" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {ttlData.checked_at && (
            <p className="text-[10px] text-gray-400 text-right">
              Last checked: {new Date(ttlData.checked_at).toLocaleString()}
            </p>
          )}
        </div>
      )}
    </GlassCard>
  );
}

const ALERT_TYPE_OPTIONS = [
  { label: 'All Types', value: '' },
  { label: 'Spoofed Bot Surge', value: 'spoofed_bot_surge' },
  { label: 'High Error Rate', value: 'high_error_rate' },
  { label: 'High Latency', value: 'high_latency' },
  { label: 'High Fallback Rate', value: 'high_fallback_rate' },
];

const DATE_RANGE_OPTIONS = [
  { label: 'All Time', value: '' },
  { label: 'Last 24 hours', value: '1' },
  { label: 'Last 7 days', value: '7' },
  { label: 'Last 30 days', value: '30' },
  { label: 'Last 90 days', value: '90' },
];

function AlertHistoryPanel({ adminToken }) {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [typeFilter, setTypeFilter] = useState('');
  const [dateRange, setDateRange] = useState('');
  const [ackFilter, setAckFilter] = useState(null);
  const [ackingId, setAckingId] = useState(null);
  const [ackingAll, setAckingAll] = useState(false);
  const [ackError, setAckError] = useState(null);
  const [unacknowledgedCount, setUnacknowledgedCount] = useState(0);

  const fetchAlerts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { limit: 100 };
      if (typeFilter) params.type = typeFilter;
      if (ackFilter !== null) params.acknowledged = ackFilter;
      if (dateRange) {
        const now = new Date();
        const from = new Date(now.getTime() - Number(dateRange) * 86400000);
        params.date_from = from.toISOString();
      }
      const res = await adminGetAlerts(adminToken, params);
      const fetched = res.data?.alerts || [];
      setAlerts(fetched);
      setUnacknowledgedCount(fetched.filter(a => !a.acknowledged).length);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load alert history');
    } finally {
      setLoading(false);
    }
  }, [adminToken, typeFilter, dateRange, ackFilter]);

  useEffect(() => {
    if (expanded) fetchAlerts();
  }, [expanded, fetchAlerts]);

  const handleAcknowledge = async (alertId) => {
    setAckingId(alertId);
    setAckError(null);
    try {
      await adminAcknowledgeAlert(adminToken, alertId);
      setAlerts(prev => prev.map(a => a._id === alertId ? { ...a, acknowledged: true, acknowledged_at: new Date().toISOString() } : a));
      setUnacknowledgedCount(prev => Math.max(0, prev - 1));
    } catch (err) {
      setAckError(err.response?.data?.detail || 'Failed to acknowledge alert');
    } finally {
      setAckingId(null);
    }
  };

  const handleAcknowledgeAll = async () => {
    setAckingAll(true);
    setAckError(null);
    try {
      await adminAcknowledgeAllAlerts(adminToken);
      setAlerts(prev => prev.map(a => ({ ...a, acknowledged: true, acknowledged_at: a.acknowledged_at || new Date().toISOString() })));
      setUnacknowledgedCount(0);
    } catch (err) {
      setAckError(err.response?.data?.detail || 'Failed to acknowledge alerts');
    } finally {
      setAckingAll(false);
    }
  };

  const alertTypeColor = (type) => {
    switch (type) {
      case 'spoofed_bot_surge': return { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-100' };
      case 'high_error_rate': return { bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-100' };
      case 'high_latency': return { bg: 'bg-yellow-50', text: 'text-yellow-700', border: 'border-yellow-100' };
      case 'high_fallback_rate': return { bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-100' };
      default: return { bg: 'bg-gray-50', text: 'text-gray-700', border: 'border-gray-100' };
    }
  };

  const formatType = (type) => {
    return (type || 'unknown').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  };

  return (
    <GlassCard>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-5 flex items-center justify-between hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-red-50">
            <History size={16} className="text-red-500" />
          </div>
          <div className="text-left">
            <h3 className="text-sm font-semibold text-gray-900">Alert History</h3>
            <p className="text-[10px] text-gray-400 mt-0.5">
              {loading && expanded ? 'Loading...' : `${alerts.length} alerts${unacknowledgedCount > 0 ? ` · ${unacknowledgedCount} unacknowledged` : ''}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {unacknowledgedCount > 0 && !expanded && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-red-100 text-red-700">
              {unacknowledgedCount} new
            </span>
          )}
          <AlertTriangle size={14} className={`text-gray-400 transition-transform ${expanded ? 'rotate-90' : ''}`} />
        </div>
      </button>

      {expanded && (
        <div className="border-t border-gray-100">
          <div className="p-4 flex flex-wrap items-center gap-2 border-b border-gray-50">
            <div className="flex items-center gap-1.5">
              <Filter size={12} className="text-gray-400" />
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="text-[11px] border border-gray-200 rounded-lg px-2 py-1 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-violet-200"
              >
                {ALERT_TYPE_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-1.5">
              <Calendar size={12} className="text-gray-400" />
              <select
                value={dateRange}
                onChange={(e) => setDateRange(e.target.value)}
                className="text-[11px] border border-gray-200 rounded-lg px-2 py-1 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-violet-200"
              >
                {DATE_RANGE_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-1.5">
              <select
                value={ackFilter === null ? '' : ackFilter ? 'true' : 'false'}
                onChange={(e) => setAckFilter(e.target.value === '' ? null : e.target.value === 'true')}
                className="text-[11px] border border-gray-200 rounded-lg px-2 py-1 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-violet-200"
              >
                <option value="">All Status</option>
                <option value="false">Unacknowledged</option>
                <option value="true">Acknowledged</option>
              </select>
            </div>
            <div className="flex items-center gap-1.5 ml-auto">
              {unacknowledgedCount > 0 && (
                <button
                  onClick={handleAcknowledgeAll}
                  disabled={ackingAll}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-medium bg-violet-50 text-violet-600 hover:bg-violet-100 transition-colors disabled:opacity-50"
                >
                  {ackingAll ? <Loader2 size={10} className="animate-spin" /> : <CheckCheck size={10} />}
                  Acknowledge All
                </button>
              )}
              <button
                onClick={fetchAlerts}
                disabled={loading}
                className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
              >
                <RefreshCw size={12} className={`text-gray-400 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {(error || ackError) && (
            <div className="p-4 space-y-2">
              {error && (
                <div className="flex items-center gap-2 text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">
                  <AlertTriangle size={12} />
                  {error}
                </div>
              )}
              {ackError && (
                <div className="flex items-center gap-2 text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">
                  <AlertTriangle size={12} />
                  {ackError}
                </div>
              )}
            </div>
          )}

          {loading ? (
            <div className="p-5 flex items-center gap-2 text-sm text-gray-400">
              <Loader2 size={14} className="animate-spin" />
              Loading alert history...
            </div>
          ) : alerts.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-gray-400">
              No alerts found matching the current filters
            </div>
          ) : (
            <div className="max-h-[500px] overflow-y-auto divide-y divide-gray-50">
              {alerts.map((alert) => {
                const colors = alertTypeColor(alert.type);
                const isAcking = ackingId === alert._id;
                return (
                  <div key={alert._id} className={`p-4 hover:bg-gray-50 transition-colors ${!alert.acknowledged ? 'bg-red-50/30' : ''}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap mb-1">
                          <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wider ${colors.bg} ${colors.text}`}>
                            {formatType(alert.type)}
                          </span>
                          {!alert.acknowledged && (
                            <span className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-red-100 text-red-700 text-[9px] font-semibold">
                              New
                            </span>
                          )}
                        </div>
                        <p className="text-xs font-medium text-gray-900 mt-1">{alert.title}</p>
                        <p className="text-[11px] text-gray-500 mt-0.5 line-clamp-2">{alert.body}</p>
                        {alert.threshold_snapshot && (
                          <div className="mt-2 flex items-center gap-3 text-[10px] text-gray-400">
                            <span>Metric: {alert.threshold_snapshot.metric}</span>
                            {alert.threshold_snapshot.value !== undefined && <span>Threshold: {alert.threshold_snapshot.value}</span>}
                            {alert.threshold_snapshot.actual !== undefined && <span>Actual: {alert.threshold_snapshot.actual}</span>}
                          </div>
                        )}
                        <div className="mt-2 flex items-center gap-3 text-[10px] text-gray-400">
                          <span className="flex items-center gap-1">
                            <Clock size={10} />
                            {alert.fired_at ? new Date(alert.fired_at).toLocaleString() : '—'}
                          </span>
                          {alert.acknowledged && alert.acknowledged_at && (
                            <span className="flex items-center gap-1">
                              <Check size={10} className="text-emerald-500" />
                              Ack'd {new Date(alert.acknowledged_at).toLocaleString()}
                              {alert.acknowledged_by ? ` by ${alert.acknowledged_by}` : ''}
                            </span>
                          )}
                        </div>
                      </div>
                      {!alert.acknowledged && (
                        <button
                          onClick={() => handleAcknowledge(alert._id)}
                          disabled={isAcking}
                          className="flex-shrink-0 flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-colors disabled:opacity-50"
                        >
                          {isAcking ? <Loader2 size={10} className="animate-spin" /> : <Check size={10} />}
                          Acknowledge
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </GlassCard>
  );
}

const PERIOD_OPTIONS = [
  { label: '7 days', value: 7 },
  { label: '14 days', value: 14 },
  { label: '30 days', value: 30 },
  { label: '90 days', value: 90 },
];

export default function AdminBotSecurity({ adminToken }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(7);
  const [blockedIps, setBlockedIps] = useState([]);
  const [actionLoading, setActionLoading] = useState({});
  const [blockDurationMenu, setBlockDurationMenu] = useState(null);

  const blockedSet = new Set(
    blockedIps
      .filter((b) => !b.expires_at || new Date(b.expires_at) > new Date())
      .map((b) => b.ip_hash)
  );

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [spoofRes, blockedRes] = await Promise.all([
        adminGetSpoofedBots(adminToken, days),
        adminGetBlockedIps(adminToken),
      ]);
      setData(spoofRes.data);
      setBlockedIps(blockedRes.data?.blocked_ips || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load spoofed bot data');
    } finally {
      setLoading(false);
    }
  }, [adminToken, days]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const BLOCK_DURATIONS = [
    { label: '1 hour', hours: 1 },
    { label: '6 hours', hours: 6 },
    { label: '24 hours', hours: 24 },
    { label: '7 days', hours: 168 },
    { label: '30 days', hours: 720 },
    { label: 'Permanent', hours: null },
  ];

  const handleBlock = async (ipHash, expiresIn = null) => {
    setBlockDurationMenu(null);
    setActionLoading((prev) => ({ ...prev, [ipHash]: 'blocking' }));
    try {
      await adminBlockIp(adminToken, ipHash, 'repeat_spoof_offender', expiresIn);
      const entry = { ip_hash: ipHash, blocked_at: new Date().toISOString(), reason: 'repeat_spoof_offender' };
      if (expiresIn) {
        entry.expires_at = new Date(Date.now() + expiresIn * 3600000).toISOString();
      }
      setBlockedIps((prev) => [...prev, entry]);
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to block IP');
    } finally {
      setActionLoading((prev) => ({ ...prev, [ipHash]: null }));
    }
  };

  const handleUnblock = async (ipHash) => {
    setActionLoading((prev) => ({ ...prev, [ipHash]: 'unblocking' }));
    try {
      await adminUnblockIp(adminToken, ipHash);
      setBlockedIps((prev) => prev.filter((b) => b.ip_hash !== ipHash));
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to unblock IP');
    } finally {
      setActionLoading((prev) => ({ ...prev, [ipHash]: null }));
    }
  };

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-40 gap-3">
        <Loader2 className="w-5 h-5 animate-spin text-violet-500" />
        <span className="text-sm text-gray-400">Loading bot security data...</span>
      </div>
    );
  }

  if (error && !data) {
    return (
      <GlassCard className="p-6">
        <div className="flex items-center gap-3 text-red-500">
          <AlertTriangle size={18} />
          <p className="text-sm">{error}</p>
        </div>
        <button
          onClick={fetchData}
          className="mt-3 text-sm text-violet-600 hover:text-violet-800 flex items-center gap-1.5"
        >
          <RefreshCw size={13} /> Retry
        </button>
      </GlassCard>
    );
  }

  const realtime = data?.realtime || {};
  const dailyCounts = data?.daily_counts || [];
  const topBots = data?.by_claimed_bot || [];
  const offenders = data?.repeat_offender_ips || [];
  const recent = data?.recent_attempts || [];

  const rpmColor = (realtime.spoof_rpm || 0) > 10 ? '#ef4444' : (realtime.spoof_rpm || 0) > 3 ? '#f59e0b' : '#10b981';

  return (
    <div className="space-y-6 max-w-7xl">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-red-50">
            <Shield size={20} className="text-red-500" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-gray-900">Bot Security</h2>
            <p className="text-xs text-gray-400">Spoofed bot detection & monitoring</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="text-xs border border-gray-200 rounded-lg px-3 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-violet-200"
          >
            {PERIOD_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-violet-50 text-violet-600 hover:bg-violet-100 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard
          label="Spoof RPM"
          value={realtime.spoof_rpm ?? 0}
          icon={TrendingUp}
          color={rpmColor}
          pulse={(realtime.spoof_rpm || 0) > 0}
        />
        <StatCard
          label="Session Total"
          value={realtime.session_total ?? 0}
          icon={Shield}
          color="#8b5cf6"
        />
        <StatCard
          label={`Period Total (${days}d)`}
          value={data?.period_total ?? 0}
          icon={AlertTriangle}
          color="#f59e0b"
        />
        <StatCard
          label="Repeat Offenders"
          value={offenders.length}
          icon={Hash}
          color="#ef4444"
        />
        <StatCard
          label="Blocked IPs"
          value={blockedIps.length}
          icon={Ban}
          color="#dc2626"
        />
      </div>

      <AlertThresholdPanel adminToken={adminToken} />

      <AlertHistoryPanel adminToken={adminToken} />

      <TtlMonitorPanel adminToken={adminToken} />

      <GlassCard>
        <div className="p-5 pb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <TrendingUp size={14} className="text-violet-500" />
            Daily Spoof Attempts
          </h3>
          <span className="text-[10px] text-gray-400 uppercase tracking-wider">Last {days} days</span>
        </div>
        <div className="px-3 pb-4" style={{ height: 260 }}>
          {dailyCounts.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={dailyCounts}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  tickFormatter={(v) => {
                    const d = new Date(v);
                    return `${d.getMonth() + 1}/${d.getDate()}`;
                  }}
                />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}
                  labelFormatter={(v) => new Date(v).toLocaleDateString()}
                />
                <Line
                  type="monotone"
                  dataKey="count"
                  stroke="#8b5cf6"
                  strokeWidth={2}
                  dot={{ r: 3, fill: '#8b5cf6' }}
                  activeDot={{ r: 5, fill: '#7c3aed' }}
                  name="Attempts"
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-full text-sm text-gray-400">
              No data for this period
            </div>
          )}
        </div>
      </GlassCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <GlassCard>
          <div className="p-5 pb-3">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <Bot size={14} className="text-violet-500" />
              Top Claimed Bots
            </h3>
          </div>
          {topBots.length > 0 ? (
            <>
              <div className="px-3 pb-2" style={{ height: 220 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={topBots.slice(0, 10)} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 10, fill: '#94a3b8' }} allowDecimals={false} />
                    <YAxis
                      type="category"
                      dataKey="bot"
                      tick={{ fontSize: 10, fill: '#64748b' }}
                      width={120}
                    />
                    <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }} />
                    <Bar dataKey="count" fill="#8b5cf6" radius={[0, 4, 4, 0]} name="Attempts" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="border-t border-gray-100 max-h-48 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-400 uppercase tracking-wider">
                      <th className="text-left px-5 py-2 font-medium">Bot Name</th>
                      <th className="text-right px-5 py-2 font-medium">Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topBots.map((b, i) => (
                      <tr key={i} className="border-t border-gray-50 hover:bg-gray-50">
                        <td className="px-5 py-2 text-gray-700 font-medium">{b.bot}</td>
                        <td className="px-5 py-2 text-right text-gray-500">{b.count.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="px-5 pb-5 text-sm text-gray-400">No spoofed bots detected</div>
          )}
        </GlassCard>

        <GlassCard>
          <div className="p-5 pb-3">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <Hash size={14} className="text-red-500" />
              Repeat Offender IPs
            </h3>
            <p className="text-[10px] text-gray-400 mt-0.5">IPs with 5+ spoofing attempts</p>
          </div>
          {offenders.length > 0 ? (
            <div className="border-t border-gray-100 max-h-[380px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-400 uppercase tracking-wider">
                    <th className="text-left px-5 py-2 font-medium">IP Hash</th>
                    <th className="text-right px-5 py-2 font-medium">Attempts</th>
                    <th className="text-left px-5 py-2 font-medium">Claimed Bots</th>
                    <th className="text-center px-5 py-2 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {offenders.map((o, i) => {
                    const isBlocked = blockedSet.has(o.ip_hash);
                    const busy = actionLoading[o.ip_hash];
                    return (
                      <tr key={i} className="border-t border-gray-50 hover:bg-gray-50">
                        <td className="px-5 py-2 text-gray-600 font-mono text-[11px]">
                          {o.ip_hash ? `${o.ip_hash.slice(0, 12)}...` : '—'}
                        </td>
                        <td className="px-5 py-2 text-right">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                            o.attempts >= 50 ? 'bg-red-100 text-red-700' :
                            o.attempts >= 20 ? 'bg-amber-100 text-amber-700' :
                            'bg-gray-100 text-gray-600'
                          }`}>
                            {o.attempts ?? 0}
                          </span>
                        </td>
                        <td className="px-5 py-2">
                          <div className="flex flex-wrap gap-1">
                            {(o.claimed_bots || []).slice(0, 3).map((bot, j) => (
                              <span key={j} className="inline-flex items-center px-1.5 py-0.5 rounded bg-violet-50 text-violet-600 text-[10px]">
                                {bot}
                              </span>
                            ))}
                            {(o.claimed_bots || []).length > 3 && (
                              <span className="text-[10px] text-gray-400">+{o.claimed_bots.length - 3}</span>
                            )}
                          </div>
                        </td>
                        <td className="px-5 py-2 text-center">
                          {isBlocked ? (
                            <button
                              onClick={() => handleUnblock(o.ip_hash)}
                              disabled={!!busy}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-colors disabled:opacity-50"
                            >
                              {busy === 'unblocking' ? <Loader2 size={10} className="animate-spin" /> : <Unlock size={10} />}
                              Unblock
                            </button>
                          ) : (
                            <div className="relative">
                              <button
                                onClick={() => setBlockDurationMenu(blockDurationMenu === o.ip_hash ? null : o.ip_hash)}
                                disabled={!!busy}
                                className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium bg-red-50 text-red-700 hover:bg-red-100 transition-colors disabled:opacity-50"
                              >
                                {busy === 'blocking' ? <Loader2 size={10} className="animate-spin" /> : <Ban size={10} />}
                                Block
                              </button>
                              {blockDurationMenu === o.ip_hash && (
                                <div className="absolute right-0 top-full mt-1 z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[120px]">
                                  {BLOCK_DURATIONS.map((d) => (
                                    <button
                                      key={d.label}
                                      onClick={() => handleBlock(o.ip_hash, d.hours)}
                                      className="block w-full text-left px-3 py-1.5 text-[11px] text-gray-700 hover:bg-gray-50 transition-colors"
                                    >
                                      {d.label}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="px-5 pb-5 text-sm text-gray-400">No repeat offenders found</div>
          )}
        </GlassCard>
      </div>

      {blockedIps.length > 0 && (
        <GlassCard>
          <div className="p-5 pb-3">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <Ban size={14} className="text-red-500" />
              Blocked IPs
            </h3>
            <p className="text-[10px] text-gray-400 mt-0.5">{blockedIps.length} IP{blockedIps.length !== 1 ? 's' : ''} currently blocked</p>
          </div>
          <div className="border-t border-gray-100 max-h-[300px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-400 uppercase tracking-wider">
                  <th className="text-left px-5 py-2 font-medium">IP Hash</th>
                  <th className="text-left px-5 py-2 font-medium">Reason</th>
                  <th className="text-left px-5 py-2 font-medium">Blocked At</th>
                  <th className="text-left px-5 py-2 font-medium">Expires</th>
                  <th className="text-left px-5 py-2 font-medium">Blocked By</th>
                  <th className="text-center px-5 py-2 font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {blockedIps.map((b, i) => {
                  const busy = actionLoading[b.ip_hash];
                  return (
                    <tr key={i} className="border-t border-gray-50 hover:bg-gray-50">
                      <td className="px-5 py-2 text-gray-600 font-mono text-[11px]">
                        {b.ip_hash ? `${b.ip_hash.slice(0, 12)}...` : '—'}
                      </td>
                      <td className="px-5 py-2 text-gray-500">
                        <span className="flex items-center gap-1.5">
                          {b.reason || '—'}
                          {b.reason === 'auto_threshold' && (
                            <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 text-[9px] font-semibold uppercase tracking-wider">Auto</span>
                          )}
                        </span>
                      </td>
                      <td className="px-5 py-2 text-gray-500 whitespace-nowrap">
                        {b.blocked_at ? new Date(b.blocked_at).toLocaleString() : '—'}
                      </td>
                      <td className="px-5 py-2 whitespace-nowrap">
                        {b.expires_at ? (
                          new Date(b.expires_at) <= new Date() ? (
                            <span className="text-amber-600 text-[10px] font-medium">Expired</span>
                          ) : (
                            <span className="text-gray-500">{new Date(b.expires_at).toLocaleString()}</span>
                          )
                        ) : (
                          <span className="text-gray-400 text-[10px]">Permanent</span>
                        )}
                      </td>
                      <td className="px-5 py-2 text-gray-500">{b.blocked_by || '—'}</td>
                      <td className="px-5 py-2 text-center">
                        <button
                          onClick={() => handleUnblock(b.ip_hash)}
                          disabled={!!busy}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-colors disabled:opacity-50"
                        >
                          {busy === 'unblocking' ? <Loader2 size={10} className="animate-spin" /> : <Unlock size={10} />}
                          Unblock
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}

      <GlassCard>
        <div className="p-5 pb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Clock size={14} className="text-violet-500" />
            Recent Spoof Attempts
          </h3>
          <span className="text-[10px] text-gray-400">Latest 50</span>
        </div>
        {recent.length > 0 ? (
          <div className="border-t border-gray-100 max-h-[420px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-white">
                <tr className="text-gray-400 uppercase tracking-wider">
                  <th className="text-left px-5 py-2 font-medium">Time</th>
                  <th className="text-left px-5 py-2 font-medium">Claimed Bot</th>
                  <th className="text-left px-5 py-2 font-medium">IP Hash</th>
                  <th className="text-left px-5 py-2 font-medium">Path</th>
                  <th className="text-left px-5 py-2 font-medium">User Agent</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((r, i) => (
                  <tr key={i} className="border-t border-gray-50 hover:bg-gray-50">
                    <td className="px-5 py-2 text-gray-500 whitespace-nowrap">
                      {r.timestamp ? new Date(r.timestamp).toLocaleString() : r.date || '—'}
                    </td>
                    <td className="px-5 py-2">
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-red-50 text-red-600 text-[10px] font-medium">
                        {r.claimed_bot || 'Unknown'}
                      </span>
                    </td>
                    <td className="px-5 py-2 text-gray-600 font-mono text-[11px]">
                      {r.ip_hash ? `${r.ip_hash.slice(0, 12)}...` : '—'}
                    </td>
                    <td className="px-5 py-2 text-gray-600 max-w-[200px] truncate" title={r.path}>
                      {r.path || '—'}
                    </td>
                    <td className="px-5 py-2 text-gray-400 max-w-[200px] truncate" title={r.user_agent}>
                      {r.user_agent || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="px-5 pb-5 text-sm text-gray-400">No recent attempts</div>
        )}
      </GlassCard>

      {realtime.session_by_bot && Object.keys(realtime.session_by_bot).length > 0 && (
        <GlassCard>
          <div className="p-5 pb-3">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <Eye size={14} className="text-amber-500" />
              Real-time Session Breakdown
            </h3>
            <p className="text-[10px] text-gray-400 mt-0.5">Spoofed requests in current server session</p>
          </div>
          <div className="border-t border-gray-100">
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 p-5">
              {Object.entries(realtime.session_by_bot)
                .sort(([, a], [, b]) => b - a)
                .map(([bot, count]) => (
                  <div key={bot} className="rounded-xl border border-gray-100 p-3 bg-gray-50">
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider truncate">{bot}</p>
                    <p className="text-lg font-bold text-gray-900 mt-1">{count.toLocaleString()}</p>
                  </div>
                ))}
            </div>
          </div>
        </GlassCard>
      )}
    </div>
  );
}
