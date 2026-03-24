import { useState, useEffect } from 'react';
import { Users, MessageSquare, BookOpen, Zap, Loader2, Activity, ArrowRight, PenTool, Settings } from 'lucide-react';
import { adminGetDashboard, adminGetActivityLog } from '@/utils/api';

function StatCard({ label, value, icon: Icon, color }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5" data-testid="dashboard-stat-card">
      <div className="flex items-center justify-between mb-3">
        <p className="text-slate-500 text-sm">{label}</p>
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${color}`}>
          <Icon size={16} className="text-white" />
        </div>
      </div>
      <p className="text-2xl font-semibold text-white">{value?.toLocaleString() || 0}</p>
    </div>
  );
}

function formatTimeAgo(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

export default function AdminDashboard({ adminToken, onNavigate }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activities, setActivities] = useState([]);

  useEffect(() => {
    Promise.all([
      adminGetDashboard(adminToken).then((res) => setData(res.data)).catch(() => {}),
      adminGetActivityLog(adminToken).then((res) => {
        const logs = res.data?.logs || res.data || [];
        setActivities(Array.isArray(logs) ? logs.slice(0, 5) : []);
      }).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, [adminToken]);

  if (loading) {
    return (
      <div className="flex justify-center p-10">
        <Loader2 size={24} className="animate-spin text-slate-400" />
      </div>
    );
  }

  const quickActions = [
    { id: 'users', label: 'View Users', icon: Users, color: 'from-violet-600 to-violet-500' },
    { id: 'content', label: 'Content Editor', icon: PenTool, color: 'from-blue-600 to-blue-500' },
    { id: 'settings', label: 'Settings', icon: Settings, color: 'from-emerald-600 to-emerald-500' },
  ];

  return (
    <div className="p-6 space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Users" value={data?.total_users} icon={Users} color="bg-violet-600" />
        <StatCard label="Conversations" value={data?.total_conversations} icon={MessageSquare} color="bg-blue-600" />
        <StatCard label="Messages" value={data?.total_messages} icon={Zap} color="bg-emerald-600" />
        <StatCard label="Subjects" value={data?.total_subjects} icon={BookOpen} color="bg-amber-600" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {quickActions.map((action) => (
          <button
            key={action.id}
            onClick={() => onNavigate?.(action.id)}
            className="flex items-center justify-between p-4 bg-slate-900 border border-slate-800 rounded-xl hover:border-slate-700 transition-all group"
            data-testid={`quick-action-${action.id}`}
          >
            <div className="flex items-center gap-3">
              <div className={`w-9 h-9 rounded-lg bg-gradient-to-br ${action.color} flex items-center justify-center`}>
                <action.icon size={16} className="text-white" />
              </div>
              <span className="text-sm font-medium text-white">{action.label}</span>
            </div>
            <ArrowRight size={16} className="text-slate-600 group-hover:text-slate-400 transition-colors" />
          </button>
        ))}
      </div>

      {data?.plan_distribution && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h3 className="text-slate-300 font-semibold mb-4">Plan Distribution</h3>
          <div className="grid grid-cols-3 gap-4">
            {Object.entries(data.plan_distribution).map(([plan, count]) => (
              <div key={plan} className="text-center p-4 bg-slate-800/50 rounded-xl">
                <p className="text-2xl font-bold text-white">{count}</p>
                <p className="text-slate-500 text-sm capitalize">{plan}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6" data-testid="recent-activity">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Activity size={16} className="text-violet-400" />
            <h3 className="text-slate-300 font-semibold">Recent Activity</h3>
          </div>
          <button
            onClick={() => onNavigate?.('activitylog')}
            className="text-xs text-violet-400 hover:text-violet-300 transition-colors"
          >
            View all
          </button>
        </div>
        {activities.length === 0 ? (
          <p className="text-slate-600 text-sm text-center py-4">No recent activity</p>
        ) : (
          <div className="space-y-2">
            {activities.map((entry, idx) => (
              <div
                key={entry._id || entry.id || idx}
                className="flex items-center justify-between py-2.5 px-3 rounded-lg bg-slate-800/30"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-1.5 h-1.5 rounded-full bg-violet-400 flex-shrink-0" />
                  <div className="min-w-0">
                    <p className="text-sm text-white/80 truncate">
                      {entry.action || entry.message || entry.type || 'Activity'}
                    </p>
                    {entry.details && (
                      <p className="text-xs text-slate-500 truncate">{typeof entry.details === 'string' ? entry.details : JSON.stringify(entry.details)}</p>
                    )}
                  </div>
                </div>
                <span className="text-xs text-slate-600 flex-shrink-0 ml-3">
                  {formatTimeAgo(entry.timestamp || entry.created_at || entry.date)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
