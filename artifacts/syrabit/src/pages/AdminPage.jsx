import { useState, useEffect, lazy, Suspense } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  LayoutDashboard, GitBranch, BookOpen, Users,
  MessageSquare, TrendingUp, CreditCard, Bell, Key,
  Shield, Settings, Activity, HeartPulse, LogOut,
  ChevronLeft, ChevronRight, Loader2, Globe,
  Crown, Cpu, Layers, Zap, BarChart2, ThumbsUp,
  ExternalLink,
} from 'lucide-react';
import axios from 'axios';
import { adminVerify, adminLogout, adminGetSettings, API_BASE } from '@/utils/api';
import { toast } from 'sonner';

const AdminDashboard     = lazy(() => import('@/components/admin/AdminDashboard'));
const AdminRoadmap       = lazy(() => import('@/components/admin/AdminRoadmap'));
const AdminContentHub    = lazy(() => import('@/components/admin/AdminContentHub'));
const AdminUsers         = lazy(() => import('@/components/admin/AdminUsers'));
const AdminConversations = lazy(() => import('@/components/admin/AdminConversations'));
const AdminAnalytics     = lazy(() => import('@/components/admin/AdminAnalytics'));
const AdminPlans         = lazy(() => import('@/components/admin/AdminPlans'));
const AdminNotifications = lazy(() => import('@/components/admin/AdminNotifications'));
const AdminApiConfig     = lazy(() => import('@/components/admin/AdminApiConfig'));
const AdminGoogleAuth    = lazy(() => import('@/components/admin/AdminGoogleAuth'));
const AdminSettings      = lazy(() => import('@/components/admin/AdminSettings'));
const AdminRateLimits    = lazy(() => import('@/components/admin/AdminRateLimits'));
const AdminActivityLog   = lazy(() => import('@/components/admin/AdminActivityLog'));
const AdminHealth        = lazy(() => import('@/components/admin/AdminHealth'));
const AdminSeoManager    = lazy(() => import('@/components/admin/AdminSeoManager'));
const AdminMonetization  = lazy(() => import('@/components/admin/AdminMonetization'));
const AdminVertexPanel   = lazy(() => import('@/components/admin/AdminVertexPanel'));
const AdminAutomation    = lazy(() => import('@/components/admin/AdminAutomation'));
const AdminIntelligence  = lazy(() => import('@/components/admin/AdminIntelligence'));
const AdminFeedback      = lazy(() => import('@/components/admin/AdminFeedback'));

const SECTIONS = [
  { id: 'dashboard',     icon: LayoutDashboard, label: 'Dashboard',        group: 'main'     },
  { id: 'roadmap',       icon: GitBranch,       label: 'Roadmap',           group: 'main'     },
  { id: 'contenthub',    icon: Layers,          label: 'Content Editor',    group: 'content'  },
  { id: 'seomanager',    icon: Globe,           label: 'SEO Manager',       group: 'content'  },
  { id: 'vertex',        icon: Cpu,             label: 'Vertex AI Studio',  group: 'content'  },
  { id: 'automation',    icon: Zap,             label: 'Automation',        group: 'content'  },
  { id: 'users',         icon: Users,           label: 'Users',             group: 'audience' },
  { id: 'conversations', icon: MessageSquare,   label: 'Conversations',     group: 'audience' },
  { id: 'feedback',      icon: ThumbsUp,        label: 'Chat Feedback',     group: 'audience' },
  { id: 'analytics',     icon: TrendingUp,      label: 'Analytics',         group: 'insights' },
  { id: 'monetization',  icon: Crown,           label: 'Monetization',      group: 'insights' },
  { id: 'plans',         icon: CreditCard,      label: 'Plans & Credits',   group: 'insights' },
  { id: 'intelligence',  icon: BarChart2,       label: 'Intelligence',      group: 'insights' },
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
  contenthub:    AdminContentHub,
  seomanager:    AdminSeoManager,
  automation:    AdminAutomation,
  users:         AdminUsers,
  conversations: AdminConversations,
  feedback:      AdminFeedback,
  analytics:     AdminAnalytics,
  monetization:  AdminMonetization,
  plans:         AdminPlans,
  notifications: AdminNotifications,
  apiconfig:     AdminApiConfig,
  googleauth:    AdminGoogleAuth,
  settings:      AdminSettings,
  ratelimits:    AdminRateLimits,
  activitylog:   AdminActivityLog,
  health:        AdminHealth,
  vertex:        AdminVertexPanel,
  intelligence:  AdminIntelligence,
};

export default function AdminPage() {
  const navigate = useNavigate();
  const [activeSection, setActiveSection] = useState('dashboard');
  const [navContext, setNavContext]        = useState(null);
  const [collapsed, setCollapsed]         = useState(false);
  const [verifying, setVerifying]         = useState(true);
  const [sysStatus, setSysStatus]         = useState('ok');

  const [adminEmail, setAdminEmail] = useState('');
  const [adminName,  setAdminName]  = useState('Admin');
  const [adminToken, setAdminToken] = useState(null);

  useEffect(() => {
    const storedToken = localStorage.getItem('admin_token');
    adminVerify(storedToken)
      .then((res) => {
        if (res.data?.name) setAdminName(res.data.name);
        if (res.data?.email) setAdminEmail(res.data.email);
        if (res.data?.access_token) localStorage.setItem('admin_token', res.data.access_token);
        setAdminToken(res.data?.access_token || storedToken || 'verified');
        setVerifying(false);
      })
      .catch(() => {
        localStorage.removeItem('admin_token');
        navigate('/admin/login');
      });
  }, [navigate]);

  useEffect(() => {
    if (verifying) return;
    const id = setInterval(() => {
      const t = localStorage.getItem('admin_token');
      adminVerify(t)
        .then((res) => {
          if (res.data?.access_token) localStorage.setItem('admin_token', res.data.access_token);
        })
        .catch(() => {
          localStorage.removeItem('admin_token');
          toast.error('Session expired. Please log in again.');
          navigate('/admin/login');
        });
    }, 20 * 60 * 1000);
    return () => clearInterval(id);
  }, [verifying, navigate]);

  useEffect(() => {
    if (verifying) return;
    const checkStatus = async () => {
      try {
        const [healthRes, settingsRes] = await Promise.allSettled([
          axios.get(`${API_BASE}/health`, { withCredentials: true }),
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
    await adminLogout().catch(() => {});
    localStorage.removeItem('admin_token');
    setAdminToken(null);
    toast.success('Logged out');
    navigate('/admin/login');
  };

  if (verifying) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center"
        style={{ background: 'linear-gradient(145deg, #050510 0%, #0a0a1a 50%, #080816 100%)' }}>
        <div className="relative">
          <div className="absolute inset-0 rounded-full blur-xl opacity-30" style={{ background: 'radial-gradient(circle, #7c3aed 0%, transparent 70%)' }} />
          <Loader2 className="w-8 h-8 animate-spin text-violet-400 mb-3 relative" />
        </div>
        <p className="text-sm text-white/30 mt-4">Verifying admin session...</p>
      </div>
    );
  }

  const ActiveComponent = SECTION_COMPONENTS[activeSection] || AdminDashboard;
  const activeLabel = SECTIONS.find((s) => s.id === activeSection)?.label || 'Admin';

  const statusConfig = {
    ok:          { label: 'All Systems Operational', dot: 'bg-emerald-400', text: 'text-emerald-400', border: 'border-emerald-500/20', bg: 'bg-emerald-500/[0.06]' },
    warn:        { label: 'Setup Required',          dot: 'bg-amber-400',   text: 'text-amber-400',   border: 'border-amber-500/20',   bg: 'bg-amber-500/[0.06]'   },
    maintenance: { label: 'Maintenance Mode',        dot: 'bg-red-400',     text: 'text-red-400',     border: 'border-red-500/20',     bg: 'bg-red-500/[0.06]'     },
  };
  const sc = statusConfig[sysStatus];

  return (
    <div className="min-h-screen flex" style={{ background: 'linear-gradient(145deg, #050510 0%, #0a0a1a 50%, #080816 100%)' }} data-testid="admin-dashboard">
      <aside
        className="flex flex-col h-screen sticky top-0 transition-all duration-300 flex-shrink-0 z-20"
        style={{
          width: collapsed ? 68 : 252,
          background: 'linear-gradient(180deg, rgba(13,13,28,0.98) 0%, rgba(8,8,20,0.98) 100%)',
          borderRight: '1px solid rgba(139,92,246,0.08)',
          backdropFilter: 'blur(20px)',
        }}
      >
        <div
          className="flex items-center px-4 border-b border-white/[0.04]"
          style={{ height: 60 }}
        >
          {collapsed ? (
            <div className="w-9 h-9 rounded-xl flex items-center justify-center mx-auto" style={{ background: 'linear-gradient(135deg, rgba(124,58,237,0.2), rgba(139,92,246,0.1))' }}>
              <img src="/logo.webp" alt="S" width="24" height="24" className="w-6 h-6 rounded-lg object-cover" />
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <div className="relative">
                <div className="absolute -inset-1 rounded-xl blur-md opacity-40" style={{ background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)' }} />
                <div className="relative w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: 'linear-gradient(135deg, rgba(124,58,237,0.25), rgba(139,92,246,0.15))' }}>
                  <img src="/logo.webp" alt="Syrabit.ai" width="24" height="24" className="w-6 h-6 rounded-lg object-cover" />
                </div>
              </div>
              <div>
                <p className="text-sm font-bold text-white tracking-tight" style={{ lineHeight: 1.2 }}>Syrabit.ai</p>
                <p className="text-[9px] font-semibold tracking-[0.15em] flex items-center gap-1" style={{ color: 'rgba(167,139,250,0.7)' }}>
                  CONTROL CENTER
                </p>
              </div>
            </div>
          )}
        </div>

        <nav className="flex-1 overflow-y-auto py-3 px-2.5 space-y-0.5 scrollbar-thin">
          {GROUPS.map((group) => {
            const groupSections = SECTIONS.filter((s) => s.group === group);
            const label = GROUP_LABELS[group];
            return (
              <div key={group}>
                {label && !collapsed && (
                  <div className="flex items-center gap-2 px-3 py-2 mt-3 mb-0.5">
                    <div className="h-px flex-1" style={{ background: 'linear-gradient(90deg, rgba(139,92,246,0.15), transparent)' }} />
                    <p className="text-[9px] font-bold tracking-[0.15em] flex-shrink-0"
                      style={{ color: 'rgba(167,139,250,0.35)' }}>
                      {label}
                    </p>
                    <div className="h-px flex-1" style={{ background: 'linear-gradient(90deg, transparent, rgba(139,92,246,0.15))' }} />
                  </div>
                )}
                {collapsed && label && <div className="h-px mx-3 my-2" style={{ background: 'rgba(139,92,246,0.1)' }} />}
                {groupSections.map(({ id, icon: Icon, label: sectionLabel }) => {
                  const isActive = activeSection === id;
                  return (
                    <button
                      key={id}
                      onClick={() => setActiveSection(id)}
                      className="relative w-full flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 text-left group"
                      style={{
                        background: isActive
                          ? 'linear-gradient(135deg, rgba(124,58,237,0.18) 0%, rgba(139,92,246,0.08) 100%)'
                          : 'transparent',
                        color: isActive ? 'rgb(196,181,253)' : 'rgba(255,255,255,0.35)',
                        fontWeight: isActive ? 600 : 400,
                      }}
                      data-testid={`admin-nav-${id}`}
                    >
                      {isActive && (
                        <div
                          className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full"
                          style={{ background: 'linear-gradient(180deg, #a78bfa, #7c3aed)' }}
                        />
                      )}
                      <div
                        className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 transition-all duration-200"
                        style={{
                          background: isActive ? 'rgba(124,58,237,0.2)' : 'transparent',
                        }}
                      >
                        <Icon size={15} className="flex-shrink-0 transition-colors duration-200"
                          style={{ color: isActive ? '#a78bfa' : 'inherit' }} />
                      </div>
                      {!collapsed && (
                        <span className="text-[13px] truncate group-hover:text-white/60 transition-colors duration-200">{sectionLabel}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </nav>

        <div className="border-t border-white/[0.04] px-2.5 py-3 space-y-1">
          {!collapsed && (
            <div className="flex items-center gap-2.5 px-3 py-2 mb-1 rounded-xl" style={{ background: 'rgba(124,58,237,0.06)' }}>
              <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ background: 'linear-gradient(135deg, #7c3aed, #6d28d9)' }}>
                <span className="text-xs font-bold text-white">{adminName?.charAt(0)?.toUpperCase() || 'A'}</span>
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs text-white/70 font-medium truncate">{adminName}</p>
                <p className="text-[10px] text-white/25 truncate">{adminEmail || 'Active session'}</p>
              </div>
            </div>
          )}
          <Link to="/library">
            <button className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs text-white/25 hover:text-white/50 hover:bg-white/[0.03] transition-all duration-200">
              <ExternalLink size={13} className="flex-shrink-0" />
              {!collapsed && <span>Student View</span>}
            </button>
          </Link>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs transition-all duration-200 hover:bg-red-500/[0.06]"
            style={{ color: 'rgba(248,113,113,0.6)' }}
          >
            <LogOut size={13} className="flex-shrink-0" />
            {!collapsed && <span>Logout</span>}
          </button>
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="w-full flex items-center justify-center py-1.5 rounded-xl text-white/15 hover:text-white/30 hover:bg-white/[0.02] transition-all duration-200"
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header
          className="flex items-center justify-between px-6 border-b flex-shrink-0 z-10"
          style={{
            height: 60,
            background: 'rgba(8,8,20,0.80)',
            backdropFilter: 'blur(24px)',
            borderColor: 'rgba(255,255,255,0.04)',
          }}
        >
          <div className="flex items-center gap-3">
            <h1 className="text-sm font-semibold text-white/90">{activeLabel}</h1>
            <span className="text-white/10">|</span>
            <span className="text-xs text-white/20 flex items-center gap-1.5">
              <img src="/logo.webp" alt="" width="14" height="14" className="w-3.5 h-3.5 rounded-sm inline-block opacity-50" />
              Syrabit.ai
            </span>
          </div>

          <div
            className={`flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-medium border ${sc.text} ${sc.border} ${sc.bg}`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${sc.dot} animate-pulse`} />
            <span className="text-[11px]">{sc.label}</span>
          </div>
        </header>

        <main className={`flex-1 overflow-hidden flex flex-col ${activeSection === 'contenthub' ? '' : 'overflow-y-auto p-3 sm:p-4 md:p-6'}`}>
          <Suspense fallback={
            <div className="flex items-center justify-center h-40 gap-3">
              <Loader2 className="w-5 h-5 animate-spin text-violet-400/60" />
              <span className="text-sm text-white/20">Loading section...</span>
            </div>
          }>
            <ActiveComponent
              adminToken={adminToken}
              adminName={adminName}
              onNavigate={(section, ctx = null) => {
                if (section === 'blog') {
                  setNavContext({ initialTab: 'blog' });
                  setActiveSection('contenthub');
                } else {
                  setNavContext(ctx);
                  setActiveSection(section);
                }
              }}
              navContext={activeSection === 'users' || activeSection === 'contenthub' ? navContext : null}
            />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
