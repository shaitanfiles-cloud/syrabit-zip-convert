import { TrendingUp, Eye, Users, DollarSign, Zap, Target,
  Cloud, AlertTriangle, Calendar } from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar,
} from 'recharts';
import { Card, Stat, TT, fmt, fmtInr } from './shared';

const TIME_RANGES = [
  { value: 1,  label: 'Today' },
  { value: 7,  label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
  { value: 90, label: 'Last 90 days' },
];

export default function OverviewTab({ data, vs, widgetErrors, load, mrr, predicted, growth, arpu, ltv,
  cfConnected, overviewDays, setOverviewDays }) {
  const hasDailySignup = data?.daily_signups?.some(d => d.count > 0);
  const hasPlanUsage   = data?.plan_usage && Object.keys(data.plan_usage).length > 0;
  const cf = vs.cloudflare || {};
  const dailyVisitors = cf.daily_visitors || [];
  const hasDailyCf = dailyVisitors.some(d => d.visitors > 0 || d.page_views > 0);
  const rangeLabel = TIME_RANGES.find(t => t.value === overviewDays)?.label || `Last ${overviewDays} days`;
  const cfEmptyMsg = cfConnected
    ? 'No data yet for this range'
    : 'Cloudflare analytics unavailable — check API token and Zone ID';

  return (
    <>
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1.5 text-gray-400 text-sm">
          <Calendar size={14} />
          <span>Time range:</span>
        </div>
        {TIME_RANGES.map(t => (
          <button key={t.value} onClick={() => setOverviewDays(t.value)}
            className={`px-3.5 py-1.5 rounded-xl text-xs font-medium transition-all ${
              overviewDays === t.value ? 'text-white' : 'text-gray-400 hover:text-gray-500'
            }`}
            style={overviewDays === t.value
              ? { background: 'linear-gradient(135deg, #7c3aed, #6d28d9)', boxShadow: '0 2px 12px rgba(124,58,237,0.3)' }
              : { background: '#f9fafb', border: '1px solid #e5e7eb' }
            }>
            {t.label}
          </button>
        ))}
      </div>

      {widgetErrors.overview && (
        <div className="flex items-center gap-3 p-3.5 rounded-xl" style={{
          background: 'rgba(245,158,11,0.06)',
          border: '1px solid rgba(245,158,11,0.15)',
        }}>
          <AlertTriangle size={14} className="text-amber-400 flex-shrink-0" />
          <p className="text-xs text-amber-300/80 flex-1">Overview data failed to load — some metrics unavailable.</p>
          <button onClick={() => load(true)} className="text-xs text-amber-300 hover:text-gray-900 px-2.5 py-1 rounded-lg transition-colors"
            style={{ background: 'rgba(245,158,11,0.12)' }}>Retry</button>
        </div>
      )}

      {!cfConnected && (
        <div className="flex items-start gap-3 p-4 rounded-xl" style={{
          background: 'rgba(239,68,68,0.06)',
          border: '1px solid rgba(239,68,68,0.15)',
        }}>
          <Cloud size={16} className="text-red-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-sm font-semibold text-red-500">Cloudflare analytics unavailable</p>
            <p className="text-xs text-red-400/80 mt-0.5">All visitor and page-view numbers come from Cloudflare. Check the Cloudflare API token and Zone ID environment variables.</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat icon={TrendingUp} label={`Visitors (${rangeLabel})`}
          value={(cf.total_visitors ?? 0).toLocaleString()} color="#f6821f" sub="Cloudflare" />
        <Stat icon={Users} label="Visitors Today"
          value={(cf.visitors_today ?? 0).toLocaleString()} color="#06b6d4" sub="Cloudflare" />
        <Stat icon={Eye} label="Page Views Today"
          value={(cf.page_views_today ?? 0).toLocaleString()} color="#ec4899" sub="Cloudflare" />
        <Stat icon={Users} label="Active Users" value={data?.active_users ?? 0} color="#8b5cf6" />
      </div>

      {mrr > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat icon={DollarSign} label="MRR (30d)"       value={fmtInr(mrr)}       color="#10b981" trend={growth} />
          <Stat icon={TrendingUp} label="Predicted MRR"   value={fmtInr(predicted)} color="#7c3aed" />
          <Stat icon={Target}     label="ARPU"            value={fmtInr(arpu)}       color="#f59e0b" />
          <Stat icon={Zap}        label="LTV (12-mo)"     value={fmtInr(ltv)}        color="#06b6d4" />
        </div>
      )}

      <Card title={`Daily Visitors — ${rangeLabel}`} empty={!hasDailyCf} emptyMsg={cfEmptyMsg}>
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={dailyVisitors} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f9fafb" />
            <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 11 }} tickFormatter={fmt}
              interval={Math.max(0, Math.floor(dailyVisitors.length / 8) - 1)} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
            <Tooltip {...TT} />
            <Area type="monotone" dataKey="visitors" name="Cloudflare Visitors"
              stroke="#f6821f" fill="rgba(246,130,31,0.12)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      <Card title={`Daily Page Views — ${rangeLabel}`} empty={!hasDailyCf} emptyMsg={cfEmptyMsg}>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={dailyVisitors} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f9fafb" />
            <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 11 }} tickFormatter={fmt}
              interval={Math.max(0, Math.floor(dailyVisitors.length / 8) - 1)} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
            <Tooltip {...TT} />
            <Area type="monotone" dataKey="page_views" name="Cloudflare Page Views"
              stroke="#ec4899" fill="rgba(236,72,153,0.10)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      <Card title={`Daily Signups — ${rangeLabel}`} empty={!hasDailySignup} emptyMsg="No signups in this range">
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={data.daily_signups} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f9fafb" />
            <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 11 }} tickFormatter={fmt}
              interval={Math.max(0, Math.floor((data.daily_signups?.length || 0) / 8) - 1)} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} allowDecimals={false} />
            <Tooltip {...TT} />
            <Bar dataKey="count" name="Signups" fill="#7c3aed" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>

      {hasPlanUsage && (
        <Card title="Credits Used by Plan">
          <ResponsiveContainer width="100%" height={140}>
            <BarChart data={Object.entries(data.plan_usage).map(([plan, used]) => ({ plan, used }))}
              margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f9fafb" />
              <XAxis dataKey="plan" tick={{ fill: '#9ca3af', fontSize: 11 }} />
              <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
              <Tooltip {...TT} />
              <Bar dataKey="used" name="Credits Used" fill="#7c3aed" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      )}
    </>
  );
}
