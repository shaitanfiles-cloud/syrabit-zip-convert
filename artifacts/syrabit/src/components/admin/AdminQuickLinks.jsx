/**
 * AdminQuickLinks — small "Related sections" footer strip
 * Usage: <AdminQuickLinks links={[{ id, label, icon }]} onNavigate={fn} />
 */
import {
  LayoutDashboard, BookOpen, Globe, Cpu, Users, MessageSquare,
  TrendingUp, Crown, CreditCard, Bell, Key, Shield, Settings,
  Activity, HeartPulse, GitBranch,
} from 'lucide-react';

const ICON_MAP = {
  dashboard:     LayoutDashboard,
  roadmap:       GitBranch,
  content:       BookOpen,
  seomanager:    Globe,
  vertex:        Cpu,
  users:         Users,
  conversations: MessageSquare,
  analytics:     TrendingUp,
  monetization:  Crown,
  plans:         CreditCard,
  notifications: Bell,
  apiconfig:     Key,
  googleauth:    Shield,
  settings:      Settings,
  ratelimits:    Shield,
  activitylog:   Activity,
  health:        HeartPulse,
};

const LABEL_MAP = {
  dashboard:     'Dashboard',
  roadmap:       'Roadmap',
  content:       'Content',
  seomanager:    'SEO Manager',
  vertex:        'Vertex AI',
  users:         'Users',
  conversations: 'Conversations',
  analytics:     'Analytics',
  monetization:  'Monetization',
  plans:         'Plans & Credits',
  notifications: 'Notifications',
  apiconfig:     'API Config',
  googleauth:    'Google Auth',
  settings:      'Site Settings',
  ratelimits:    'Rate Limits',
  activitylog:   'Activity Log',
  health:        'Health / Uptime',
};

export default function AdminQuickLinks({ links = [], onNavigate }) {
  if (!onNavigate || links.length === 0) return null;
  return (
    <div style={{
      marginTop: 32,
      padding: '12px 16px',
      background: 'rgba(255,255,255,0.02)',
      border: '1px solid rgba(255,255,255,0.06)',
      borderRadius: 12,
    }}>
      <p style={{ fontSize: 10, fontWeight: 700, color: 'rgba(255,255,255,0.25)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
        Related Sections
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {links.map(id => {
          const Icon = ICON_MAP[id] || LayoutDashboard;
          return (
            <button
              key={id}
              onClick={() => onNavigate(id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '6px 12px',
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: 8,
                fontSize: 12, fontWeight: 600,
                color: 'rgba(232,232,232,0.65)',
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(124,58,237,0.12)'; e.currentTarget.style.borderColor = 'rgba(124,58,237,0.30)'; e.currentTarget.style.color = '#d8b4fe'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'; e.currentTarget.style.color = 'rgba(232,232,232,0.65)'; }}
            >
              <Icon size={12} />
              {LABEL_MAP[id]}
            </button>
          );
        })}
      </div>
    </div>
  );
}
