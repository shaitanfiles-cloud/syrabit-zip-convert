import { Link, useNavigate, useLocation } from 'react-router-dom';
import { LogOut, ChevronDown, ShieldCheck, Zap, Sun, Moon, User } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { useTheme } from 'next-themes';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Badge } from '@/components/ui/badge';

const PAGE_TITLES = {
  '/library': 'Library',
  '/chat':    'AI Chat',
  '/history': 'History',
  '/profile': 'Profile',
};

const PLAN_BADGE = {
  free:    'bg-muted/80 text-muted-foreground border-border',
  starter: 'bg-primary/12 text-primary border-primary/25',
  pro:     'bg-amber-500/12 text-amber-400 border-amber-500/25',
};

export const Navbar = ({ pageTitle }) => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { theme, setTheme } = useTheme();

  const getInitials = (name) =>
    (name || 'U').split(' ').map((n) => n[0]).join('').toUpperCase().slice(0, 2);

  const title = pageTitle || PAGE_TITLES[location.pathname] || 'Syrabit.ai';
  const remaining = Math.max(0, (user?.credits_limit || 0) - (user?.credits_used || 0));
  const isFreePlan = !user?.credits_limit || user.credits_limit === 0;

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <header
      className="sticky top-0 z-40 h-14 flex items-center border-b border-border/60 gap-4 px-4 sm:px-6"
      style={{
        background: 'var(--popover-glass)',
        backdropFilter: 'blur(24px) saturate(1.8)',
        WebkitBackdropFilter: 'blur(24px) saturate(1.8)',
      }}
      data-testid="app-navbar"
    >
      <div className="flex-1">
        <h1 className="text-sm font-semibold text-foreground">{title}</h1>
      </div>

      <div className="flex items-center gap-1.5">
        {/* Credits badge */}
        {user && (
          <Badge
            variant="outline"
            className={`text-xs hidden sm:flex items-center gap-1 ${PLAN_BADGE[user.plan] || PLAN_BADGE.free}`}
            data-testid="credits-badge"
          >
            <Zap size={10} />
            {isFreePlan ? 'Upgrade to chat' : remaining > 0 ? `${remaining} credits` : '0 credits'}
          </Badge>
        )}

        {/* ── Theme toggle ── */}
        <button
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          className="flex items-center justify-center w-9 h-9 rounded-xl
            hover:bg-primary/10 text-muted-foreground hover:text-primary
            transition-all duration-200"
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          data-testid="theme-toggle-button"
        >
          {theme === 'dark'
            ? <Sun className="w-[18px] h-[18px]" aria-hidden="true" />
            : <Moon className="w-[18px] h-[18px]" aria-hidden="true" />
          }
        </button>

        {/* Profile dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              className="flex items-center gap-2 rounded-xl px-2 py-1.5 hover:bg-primary/10 transition-colors"
              data-testid="navbar-profile-button"
            >
              {/* Avatar with glow */}
              {user?.avatar_url ? (
                <img
                  src={user.avatar_url}
                  alt={user?.name || 'Avatar'}
                  className="w-7 h-7 rounded-lg object-cover"
                  style={{ boxShadow: '0 0 10px var(--glow-primary)' }}
                />
              ) : (
                <div
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-[11px] font-bold text-white"
                  style={{
                    background: 'linear-gradient(135deg, hsl(var(--primary)), #8b5cf6)',
                    boxShadow: '0 0 10px var(--glow-primary)',
                  }}
                >
                  {getInitials(user?.name)}
                </div>
              )}
              <ChevronDown size={14} className="text-muted-foreground" />
            </button>
          </DropdownMenuTrigger>

          <DropdownMenuContent align="end" className="w-52 glass-card border-border/60">
            <DropdownMenuLabel>
              <div className="flex flex-col">
                <span className="font-semibold truncate">{user?.name}</span>
                <span className="text-xs text-muted-foreground truncate">{user?.email}</span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to="/profile" className="flex items-center gap-2 cursor-pointer">
                <User size={14} /> Profile
              </Link>
            </DropdownMenuItem>
            {user?.is_admin && (
              <DropdownMenuItem asChild>
                <Link to="/admin" className="flex items-center gap-2 cursor-pointer">
                  <ShieldCheck size={14} /> Admin Panel
                </Link>
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive cursor-pointer"
              onClick={handleLogout}
              data-testid="navbar-logout-button"
            >
              <LogOut size={14} className="mr-2" /> Logout
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
};
