import { Link, useLocation, useNavigate } from 'react-router-dom';
import { BookOpen, MessageSquare, Clock, User, ChevronLeft, ChevronRight, LogOut } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/context/AuthContext';
import { cn } from '@/lib/utils';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { LogoFull, LogoMark } from '@/components/Logo';
import { pageImports } from '@/utils/pageImports';

const NAV_ITEMS = [
  { to: '/library', icon: BookOpen,      label: 'Browser',  preloadKey: 'library' },
  { to: '/chat',    icon: MessageSquare, label: 'Chat',     preloadKey: 'chat' },
  { to: '/history', icon: Clock,         label: 'History',  preloadKey: 'history' },
  { to: '/profile', icon: User,          label: 'Profile',  preloadKey: 'profile' },
];

export const Sidebar = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem('syrabit:sidebar-collapsed') === 'true'
  );

  useEffect(() => {
    localStorage.setItem('syrabit:sidebar-collapsed', String(collapsed));
  }, [collapsed]);

  const handleLogout = () => { logout(); navigate('/login'); };
  const isActive = (path) =>
    location.pathname === path || location.pathname.startsWith(path + '/');

  const handlePreload = useCallback((preloadKey) => {
    if (preloadKey && pageImports[preloadKey]) {
      pageImports[preloadKey]();
    }
  }, []);

  return (
    <TooltipProvider delayDuration={0}>
      <aside
        className={cn(
          'hidden md:flex flex-col h-screen sticky top-0 border-r border-border/60 transition-all duration-300 z-40',
          collapsed ? 'w-[64px]' : 'w-[240px]'
        )}
        style={{
          background: 'rgba(10,8,20,0.92)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
        }}
        role="navigation"
        aria-label="Main navigation"
        data-testid="app-sidebar"
      >
        {/* Logo */}
        <div
          className="flex items-center h-16 px-3 overflow-hidden"
          style={{ borderBottom: '1px solid rgba(139,92,246,0.12)' }}
        >
          <Link to="/library" className="flex items-center min-w-0">
            {collapsed ? (
              <LogoMark size="sm" />
            ) : (
              <LogoFull size="sm" />
            )}
          </Link>
        </div>

        {/* Nav items */}
        <nav className="flex-1 px-2 py-4 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map(({ to, icon: Icon, label, preloadKey }) => {
            const active = isActive(to);
            return (
              <Tooltip key={to}>
                <TooltipTrigger asChild>
                  <Link
                    to={to}
                    className={cn(
                      'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 relative group',
                      active
                        ? 'text-violet-300 nav-item-active'
                        : 'text-muted-foreground hover:text-foreground hover:translate-x-0.5'
                    )}
                    style={active ? {
                      background: 'linear-gradient(135deg, rgba(124,58,237,0.18), rgba(109,40,217,0.08))',
                      boxShadow: '0 2px 12px rgba(124,58,237,0.12)',
                    } : {}}
                    onFocus={() => handlePreload(preloadKey)}
                    onMouseEnter={e => {
                      handlePreload(preloadKey);
                      if (!active) e.currentTarget.style.background = 'rgba(139,92,246,0.08)';
                    }}
                    onMouseLeave={e => {
                      if (!active) e.currentTarget.style.background = '';
                    }}
                    data-testid={`sidebar-nav-${label.toLowerCase()}`}
                  >
                    <Icon
                      size={18}
                      className={cn('flex-shrink-0 transition-colors', active ? 'text-violet-400' : '')}
                    />
                    {!collapsed && <span>{label}</span>}
                    {active && !collapsed && (
                      <div
                        className="ml-auto w-1.5 h-1.5 rounded-full"
                        style={{
                          background: 'linear-gradient(135deg,#a78bfa,#7c3aed)',
                          boxShadow: '0 0 8px rgba(167,139,250,0.8)',
                        }}
                      />
                    )}
                  </Link>
                </TooltipTrigger>
                {collapsed && (
                  <TooltipContent side="right">{label}</TooltipContent>
                )}
              </Tooltip>
            );
          })}

        </nav>

        {/* Bottom actions */}
        <div
          className="px-2 py-3 space-y-0.5"
          style={{ borderTop: '1px solid rgba(139,92,246,0.10)' }}
        >
          {user ? <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-muted-foreground hover:text-red-400 transition-all duration-200"
                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.08)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = ''; }}
                aria-label="Log out of Syrabit.ai"
                data-testid="sidebar-logout-button"
              >
                <LogOut size={18} className="flex-shrink-0" />
                {!collapsed && <span>Logout</span>}
              </button>
            </TooltipTrigger>
            {collapsed && <TooltipContent side="right">Logout</TooltipContent>}
          </Tooltip> : <button
            onClick={() => navigate('/login')}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-muted-foreground hover:text-primary transition-all duration-200"
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(139,92,246,0.08)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = ''; }}
            aria-label="Sign in to Syrabit.ai"
          >
            <LogOut size={18} className="flex-shrink-0 rotate-180" />
            {!collapsed && <span>Sign In</span>}
          </button>}

          <button
            onClick={() => setCollapsed(!collapsed)}
            className="w-full flex items-center justify-center py-2 text-muted-foreground hover:text-foreground transition-all duration-200 rounded-xl"
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(139,92,246,0.08)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = ''; }}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            data-testid="sidebar-collapse-button"
          >
            {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
        </div>
      </aside>
    </TooltipProvider>
  );
};
