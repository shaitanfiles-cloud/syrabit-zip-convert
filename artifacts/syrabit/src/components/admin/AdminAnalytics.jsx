import { useState, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from 'recharts';
import { adminGetAnalytics } from '@/utils/api';

export default function AdminAnalytics({ adminToken }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    adminGetAnalytics(adminToken)
      .then((res) => setData(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [adminToken]);

  if (loading) return <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-slate-400" /></div>;

  if (!data) {
    return (
      <div className="p-6">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
          <p className="text-slate-400">Unable to load analytics data</p>
        </div>
      </div>
    );
  }

  const hasDailySignups = data?.daily_signups?.some(d => d.count > 0);
  const hasPlanUsage = data?.plan_usage && Object.keys(data.plan_usage).length > 0;
  const hasLibraryEvents = data?.library && (
    (data.library.top_searches?.length > 0) ||
    (data.library.most_viewed_subjects?.length > 0) ||
    (data.library.document_opens > 0)
  );

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-slate-200 font-semibold">Analytics</h2>
        <div className="flex gap-2 text-xs text-slate-500">
          <span>Total Users: {data?.total_users || 0}</span>
          <span>•</span>
          <span>Active: {data?.active_users || 0}</span>
        </div>
      </div>

      {/* Daily signups */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 className="text-slate-400 text-sm font-medium mb-4">Daily Signups (Last 7 Days)</h3>
        {hasDailySignups ? (
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={data.daily_signups}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={(d) => d.slice(5)} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', color: '#e2e8f0' }}
              />
              <Area type="monotone" dataKey="count" stroke="#7c3aed" fill="rgba(124,58,237,0.15)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-slate-600 text-sm text-center py-8">No signups in the last 7 days</p>
        )}
      </div>

      {/* Plan usage */}
      {hasPlanUsage && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="text-slate-400 text-sm font-medium mb-4">Credits Used by Plan</h3>
          <ResponsiveContainer width="100%" height={150}>
            <BarChart data={Object.entries(data.plan_usage).map(([plan, used]) => ({ plan, used }))}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="plan" tick={{ fill: '#64748b', fontSize: 11 }} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', color: '#e2e8f0' }}
              />
              <Bar dataKey="used" fill="#7c3aed" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Library analytics */}
      {hasLibraryEvents ? (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="text-slate-400 text-sm font-medium mb-4">Library Interactions</h3>
          {data.library.top_searches?.length > 0 && (
            <div className="mb-4">
              <p className="text-slate-500 text-xs mb-2">Top Searches:</p>
              <div className="space-y-1">
                {data.library.top_searches.slice(0, 5).map((item, i) => (
                  <p key={i} className="text-sm text-slate-400">{item._id || item.search_query} ({item.count || 1})</p>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="text-slate-400 text-sm font-medium mb-2">Library Interactions</h3>
          <p className="text-slate-600 text-sm">No user interactions yet. Analytics will appear as users search and explore content.</p>
        </div>
      )}
    </div>
  );
}
