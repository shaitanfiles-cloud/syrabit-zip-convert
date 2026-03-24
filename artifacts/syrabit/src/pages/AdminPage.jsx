/**
 * AdminPage — /admin
 * Full spec rebuild: AdminShell with 15 sections, 6 navigation groups,
 * collapsible sidebar, system status badge, admin name/session display.
 */
import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  LayoutDashboard, GitBranch, FolderTree, PenTool, Users,
  MessageSquare, TrendingUp, CreditCard, Bell, Key,
  Shield, Settings, Activity, HeartPulse, LogOut,
  ChevronLeft, ChevronRight, Loader2, FileText,
} from 'lucide-react';
import { adminVerify, adminLogout, adminGetSettings, API_BASE } from '@/utils/api';
import { toast } from 'sonner';

// ── Lazy-load section components ──────────────────────────────────────────────
import AdminDashboard        from '@/components/admin/AdminDashboard';
import AdminRoadmap          from '@/components/admin/AdminRoadmap';
import AdminSyllabus         from '@/components/admin/AdminSyllabus';
import AdminContentEditor    from '@/components/admin/AdminContentEditor';
import AdminUsers            from '@/components/admin/AdminUsers';
import AdminConversations    from '@/components/admin/AdminConversations';
import AdminAnalytics        from '@/components/admin/AdminAnalytics';
import AdminPlans            from '@/components/admin/AdminPlans';
import AdminNotifications    from '@/components/admin/AdminNotifications';
import AdminApiConfig        from '@/components/admin/AdminApiConfig';
import AdminGoogleAuth       from '@/components/admin/AdminGoogleAuth';
import AdminSettings         from '@/components/admin/AdminSettings';
import AdminRateLimits       from '@/components/admin/AdminRateLimits';
import AdminActivityLog      from '@/components/admin/AdminActivityLog';
import AdminHealth           from '@/components/admin/AdminHealth';

// ── Section registry ──────────────────────────────────────────────────────────
const SECTIONS = [
  { id: 'dashboard',     icon: LayoutDashboard, label: 'Dashboard',        group: 'main'     },
  { id: 'roadmap',       icon: GitBranch,       label: 'Roadmap',           group: 'main'     },
  { id: 'syllabus',      icon: FolderTree,      label: 'Syllabus',          group: 'content'  },
  { id: 'content',       icon: PenTool,         label: 'Content Editor',    group: 'content'  },
  { id: 'users',         icon: Users,           label: 'Users',             group: 'audience' },
  { id: 'conversations', icon: MessageSquare,   label: 'Conversations',     group: 'audience' },
  { id: 'analytics',     icon: TrendingUp,      label: 'Analytics',         group: 'insights' },
  { id: 'plans',         icon: CreditCard,      label: 'Plans & Credits',   group: 'insights' },
  { id: 'notifications', icon: Bell,            label: 'Notifications',     group: 'comms'    },
  { id: 'apiconfig',     icon: Key,             label: 'API Config',        group: 'system'   },
  { id: 'googleauth',    icon: Shield,          label: 'Google Auth',       group: 'system'   },
  { id: 'settings',      icon: Settings,        label: 'Site Settings',     group: 'system'   },
  { id: 'ratelimits',    icon: Shield,          label: 'Rate Limits',       group: 'system'   },
  { id: 'activitylog',   icon: Activity,        label: 'Activity Log',      group: 'system'   },
  { id: 'health',        icon: HeartPulse,      label: 'Health / Uptime',   group: 'system'   },
];

const GROUP_LABELS = {
  main:     '',
  content:  'CONTENT',
  audience: 'AUDIENCE',
  insights: 'INSIGHTS',
  comms:    'COMMS',
  system:   'SYSTEM',
};

const GROUPS = ['main', 'content', 'audience', 'insights', 'comms', 'system'];

const SECTION_COMPONENTS = {
  dashboard:     AdminDashboard,
  roadmap:       AdminRoadmap,
  syllabus:      AdminSyllabus,
  content:       AdminContentEditor,
  users:         AdminUsers,
  conversations: AdminConversations,
  analytics:     AdminAnalytics,
  plans:         AdminPlans,
  notifications: AdminNotifications,
  apiconfig:     AdminApiConfig,
  googleauth:    AdminGoogleAuth,
  settings:      AdminSettings,
  ratelimits:    AdminRateLimits,
  activitylog:   AdminActivityLog,
  health:        AdminHealth,
};

// ── AdminPage ─────────────────────────────────────────────────────────────────
export default function AdminPage() {
  const navigate = useNavigate();
  const [activeSection, setActiveSection] = useState('dashboard');
  const [collapsed, setCollapsed]         = useState(false);
  const [verifying, setVerifying]         = useState(true);
  const [sysStatus, setSysStatus]         = useState('ok'); // ok | warn | maintenance

  const [adminEmail, setAdminEmail] = useState('');
  const [adminName,  setAdminName]  = useState('Admin');
  const [adminToken, setAdminToken] = useState(null);

  // ── Verify admin session (uses httpOnly cookie via withCredentials) ───────
  useEffect(() => {
    adminVerify(null)
      .then((res) => {
        if (res.data?.name) setAdminName(res.data.name);
        if (res.data?.email) setAdminEmail(res.data.email);
        setAdminToken('verified'); // Flag that session is valid
        setVerifying(false);
      })
      .catch(() => {
        // Session invalid - redirect to login
        navigate('/admin/login');
      });
  }, [navigate]);

  // ── Dynamic system status ──────────────────────────────────────────────
  useEffect(() => {
    if (verifying) return;
    const checkStatus = async () => {
      try {
        const [healthRes, settingsRes] = await Promise.allSettled([
          fetch(`${API_BASE}/health`).then(r => r.json()).then(data => ({ data })),
          adminGetSettings(adminToken),
        ]);

        const settingsData = settingsRes.status === 'fulfilled' ? settingsRes.value?.data : null;
        if (settingsData?.maintenance_mode) {
          setSysStatus('maintenance');
          return;
        }

        const healthData = healthRes.status === 'fulfilled' ? healthRes.value?.data : null;
        if (!healthData || healthRes.status === 'rejected') {
          setSysStatus('warn');
          return;
        }
        const deps = healthData.dependencies || {};
        const hasError = Object.values(deps).some((v) => v?.status === 'error' || v?.status === 'not_configured');
        setSysStatus(hasError ? 'warn' : 'ok');
      } catch {
        setSysStatus('warn');
      }
    };
    checkStatus();
  }, [verifying, adminToken]);

  const handleLogout = async () => {
    // Call logout endpoint - this clears the httpOnly cookie server-side
    await adminLogout().catch(() => {});
    setAdminToken(null);
    toast.success('Logged out');
    navigate('/admin/login');
  };

  if (verifying) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center"
        style={{ background: '#070711' }}>
        <Loader2 className="w-8 h-8 animate-spin text-violet-400 mb-3" />
        <p className="text-sm text-white/40">Verifying admin session...</p>
      </div>
    );
  }

  const ActiveComponent = SECTION_COMPONENTS[activeSection] || AdminDashboard;
  const activeLabel = SECTIONS.find((s) => s.id === activeSection)?.label || 'Admin';

  // System status badge config
  const statusConfig = {
    ok:          { label: 'All Systems Operational', dot: 'bg-emerald-400', text: 'text-emerald-400', border: 'border-emerald-500/30' },
    warn:        { label: 'Setup Required',          dot: 'bg-amber-400',   text: 'text-amber-400',   border: 'border-amber-500/30'   },
    maintenance: { label: 'Maintenance Mode',        dot: 'bg-red-400',     text: 'text-red-400',     border: 'border-red-500/30'     },
  };
  const sc = statusConfig[sysStatus];

  return (
    <div className="min-h-screen flex" style={{ background: '#080810' }} data-testid="admin-dashboard">
      {/* ═══════════════════════════════════════════
          SIDEBAR
          ═══════════════════════════════════════════ */}
      <aside
        className="flex flex-col h-screen sticky top-0 transition-all duration-300 flex-shrink-0"
        style={{
          width: collapsed ? 64 : 240,
          background: '#0d0d1a',
          borderRight: '1px solid rgba(139,92,246,0.12)',
        }}
      >
        {/* Logo block */}
        <div className="flex items-center h-14 px-3 border-b border-white/[0.06]">
          {collapsed ? (
            <img src="/logo.png" alt="Syrabit.ai" className="w-8 h-8 rounded-lg object-cover flex-shrink-0" />
          ) : (
            <div className="flex items-center gap-2.5">
              <img src="/logo.png" alt="Syrabit.ai" className="w-8 h-8 rounded-lg object-cover flex-shrink-0" />
              <div>
                <p className="text-sm font-bold text-white shimmer-text" style={{ lineHeight: 1.2 }}>Syrabit.ai</p>
                <p className="text-[9px] text-violet-400 tracking-[0.1em] flex items-center gap-1">
                  <Shield size={8} /> ADMIN PORTAL
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
          {GROUPS.map((group) => {
            const groupSections = SECTIONS.filter((s) => s.group === group);
            const label = GROUP_LABELS[group];
            return (
              <div key={group}>
                {label && !collapsed && (
                  <p className="text-[9px] font-bold tracking-[0.12em] px-3 py-2 mt-2"
                    style={{ color: 'rgba(255,255,255,0.25)' }}>
                    {label}
                  </p>
                )}
                {groupSections.map(({ id, icon: Icon, label: sectionLabel }) => {
                  const isActive = activeSection === id;
                  return (
                    <button
                      key={id}
                      onClick={() => setActiveSection(id)}
                      className="relative w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-150 text-left"
                      style={{
                        background: isActive ? 'rgba(124,58,237,0.20)' : 'transparent',
                        color: isActive ? 'rgb(196,181,253)' : 'rgba(255,255,255,0.40)',
                        boxShadow: isActive ? '0 0 16px rgba(139,92,246,0.12)' : 'none',
                        fontWeight: isActive ? 600 : 400,
                      }}
                      data-testid={`admin-nav-${id}`}
                    >
                      {/* Active left bar */}
                      {isActive && (
                        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 rounded-r-full bg-violet-400" />
                      )}
                      <Icon size={16} className="flex-shrink-0"
                        style={{ color: isActive ? 'rgb(167,139,250)' : 'inherit' }} />
                      {!collapsed && (
                        <span className="text-sm truncate">{sectionLabel}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </nav>

        {/* Admin info + logout */}
        <div className="border-t border-white/[0.06] px-2 py-3 space-y-1">
          {!collapsed && (
            <div className="flex items-center gap-2 px-3 py-2 mb-1">
              <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0"
                style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)' }}>
                <Shield size={12} className="text-white" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs text-white/70 font-medium truncate">{adminName}</p>
                <p className="text-[10px] text-white/30 truncate">Session · 8h</p>
              </div>
            </div>
          )}
          <Link to="/library">
            <button className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs text-white/30 hover:text-white/60 hover:bg-white/5 transition-colors">
              <img src="/logo.png" alt="" className="w-3.5 h-3.5 rounded-sm object-cover flex-shrink-0" />
              {!collapsed && <span>Student View</span>}
            </button>
          </Link>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs transition-colors"
            style={{ color: 'rgba(248,113,113,0.7)' }}
          >
            <LogOut size={14} className="flex-shrink-0" />
            {!collapsed && <span>Logout</span>}
          </button>
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="w-full flex items-center justify-center py-1.5 rounded-xl text-white/20 hover:text-white/40 transition-colors"
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>
      </aside>

      {/* ═══════════════════════════════════════════
          MAIN CONTENT
          ═══════════════════════════════════════════ */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top bar */}
        <header
          className="flex items-center justify-between h-14 px-6 border-b flex-shrink-0"
          style={{
            background: 'rgba(13,13,26,0.90)',
            backdropFilter: 'blur(20px)',
            borderColor: 'rgba(255,255,255,0.06)',
          }}
        >
          <p className="text-sm font-semibold text-white">
            {activeLabel}
            <span className="text-white/20 font-normal ml-2 inline-flex items-center gap-1.5">— <img src="/logo.png" alt="" className="w-4 h-4 rounded-sm inline-block" /> Syrabit.ai</span>
          </p>

          {/* System status badge */}
          <div
            className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium border ${sc.text} ${sc.border}`}
            style={{ background: 'rgba(255,255,255,0.03)' }}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${sc.dot} animate-pulse`} />
            {sc.label}
          </div>
        </header>

        {/* Section content */}
        <main className="flex-1 overflow-y-auto p-3 sm:p-4 md:p-6">
          <ActiveComponent adminToken={adminToken} adminName={adminName} onNavigate={setActiveSection} />
        </main>
      </div>
    </div>
  );
}
