import { Link, useLocation, useNavigate } from 'react-router-dom';
import { BookOpen, MessageSquare, Clock, User, ShieldCheck, ChevronLeft, ChevronRight, LogOut } from 'lucide-react';
import { useState, useEffect } from 'react';
import { useAuth } from '@/context/AuthContext';
import { cn } from '@/lib/utils';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Separator } from '@/components/ui/separator';
import { LogoFull, LogoMark } from '@/components/Logo';

const NAV_ITEMS = [
  { to: '/library', icon: BookOpen,      label: 'Library'  },
  { to: '/chat',    icon: MessageSquare, label: 'Chat'     },
  { to: '/history', icon: Clock,         label: 'History'  },
  { to: '/profile', icon: User,          label: 'Profile'  },
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

  return (
    <TooltipProvider delayDuration={0}>
      <aside
        className={cn(
          'hidden md:flex flex-col h-screen sticky top-0 bg-card border-r border-border transition-all duration-300 z-40',
          collapsed ? 'w-[64px]' : 'w-[240px]'
        )}
        role="navigation"
        aria-label="Main navigation"
        data-testid="app-sidebar"
      >
        {/* Logo */}
        <div className="flex items-center h-16 px-3 border-b border-border overflow-hidden">
          <Link to="/library" className="flex items-center min-w-0">
            {collapsed ? (
              <LogoMark size="sm" />
            ) : (
              <LogoFull size="sm" />
            )}
          </Link>
        </div>

        {/* Nav items */}
        <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map(({ to, icon: Icon, label }) => {
            const active = isActive(to);
            return (
              <Tooltip key={to}>
                <TooltipTrigger asChild>
                  <Link
                    to={to}
                    className={cn(
                      'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 relative group',
                      active
                        ? 'bg-primary/15 text-primary nav-item-active shadow-[0_0_12px_rgba(139,92,246,0.1)]'
                        : 'text-muted-foreground hover:text-foreground hover:bg-accent/40 hover:translate-x-0.5'
                    )}
                    data-testid={`sidebar-nav-${label.toLowerCase()}`}
                  >
                    <Icon size={18} className="flex-shrink-0" />
                    {!collapsed && <span>{label}</span>}
                    {active && !collapsed && (
                      <div className="ml-auto w-1.5 h-1.5 rounded-full bg-primary shadow-[0_0_6px_hsl(var(--primary))]" />
                    )}
                  </Link>
                </TooltipTrigger>
                {collapsed && (
                  <TooltipContent side="right">{label}</TooltipContent>
                )}
              </Tooltip>
            );
          })}

          {user?.is_admin && (
            <>
              <Separator className="my-2" />
              <Tooltip>
                <TooltipTrigger asChild>
                  <Link
                    to="/admin"
                    className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-accent/40 transition-colors"
                    data-testid="sidebar-nav-admin"
                  >
                    <ShieldCheck size={18} className="flex-shrink-0" />
                    {!collapsed && <span>Admin Panel</span>}
                  </Link>
                </TooltipTrigger>
                {collapsed && <TooltipContent side="right">Admin Panel</TooltipContent>}
              </Tooltip>
            </>
          )}
        </nav>

        {/* Bottom actions */}
        <div className="px-2 py-3 border-t border-border space-y-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                aria-label="Log out of Syrabit.ai"
                data-testid="sidebar-logout-button"
              >
                <LogOut size={18} className="flex-shrink-0" />
                {!collapsed && <span>Logout</span>}
              </button>
            </TooltipTrigger>
            {collapsed && <TooltipContent side="right">Logout</TooltipContent>}
          </Tooltip>

          <button
            onClick={() => setCollapsed(!collapsed)}
            className="w-full flex items-center justify-center py-2 text-muted-foreground hover:text-foreground transition-colors rounded-xl hover:bg-accent/40"
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
