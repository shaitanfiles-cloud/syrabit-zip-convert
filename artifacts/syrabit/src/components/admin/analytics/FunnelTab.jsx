import { DollarSign, TrendingUp } from 'lucide-react';
import { Card, Stat, FUNNEL_COLORS } from './shared';

export default function FunnelTab({ funnel, widgetErrors, load }) {
  if (!funnel) {
    return (
      <Card title="Conversion Funnel" error={!!widgetErrors.funnel} onRetry={() => load(true)}
        empty={!widgetErrors.funnel} emptyMsg="Funnel data loading…" />
    );
  }

  return (
    <div className="space-y-4">
      <Card title="Conversion Funnel">
        <div className="space-y-3">
          {funnel.funnel?.map((stage, i) => (
            <div key={i}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-white text-sm font-medium">{stage.stage}</span>
                <span className="text-slate-400 text-sm">{stage.count?.toLocaleString()} ({stage.pct}%)</span>
              </div>
              <div className="h-8 rounded-lg overflow-hidden bg-slate-800">
                <div className="h-full rounded-lg transition-all duration-500"
                  style={{ width: `${stage.pct}%`, background: `linear-gradient(90deg, ${FUNNEL_COLORS[i]||'#8b5cf6'}, ${FUNNEL_COLORS[i]||'#8b5cf6'}aa)` }} />
              </div>
            </div>
          ))}
        </div>
      </Card>
      <div className="grid grid-cols-2 gap-3">
        <Stat icon={DollarSign} label="Revenue / Paid User" value={`₹${funnel.revenue_per_user || 0}`}  color="#10b981" />
        <Stat icon={TrendingUp} label="Conversion Rate"     value={`${funnel.conversion_rate || 0}%`} color="#8b5cf6" />
      </div>
    </div>
  );
}
