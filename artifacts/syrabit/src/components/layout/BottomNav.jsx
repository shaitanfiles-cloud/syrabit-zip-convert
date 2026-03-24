import { Link, useLocation } from 'react-router-dom';
import { BookOpen, MessageSquare, Clock, User, ShieldCheck } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { cn } from '@/lib/utils';

const NAV_ITEMS = [
  { to: '/library', icon: BookOpen,      label: 'Library'  },
  { to: '/chat',    icon: MessageSquare, label: 'Chat'     },
  { to: '/history', icon: Clock,         label: 'History'  },
  { to: '/profile', icon: User,          label: 'Profile'  },
];

export function BottomNav() {
  const location = useLocation();
  const { user } = useAuth();

  const isActive = (path) =>
    location.pathname === path || location.pathname.startsWith(path + '/');

  const items = user?.is_admin
    ? [...NAV_ITEMS, { to: '/admin', icon: ShieldCheck, label: 'Admin' }]
    : NAV_ITEMS;

  return (
    <nav
      className="md:hidden fixed bottom-0 left-0 right-0 z-50 border-t border-border"
      role="navigation"
      aria-label="Mobile navigation"
      style={{
        background: 'rgba(6,6,14,0.85)',
        backdropFilter: 'blur(24px)',
        WebkitBackdropFilter: 'blur(24px)',
      }}
      data-testid="app-bottom-nav"
    >
      <div className="flex items-center justify-around h-16 px-2">
        {items.map(({ to, icon: Icon, label }) => {
          const active = isActive(to);
          return (
            <Link
              key={to}
              to={to}
              className={cn(
                'flex flex-col items-center justify-center gap-1 px-3 py-2 rounded-xl text-xs font-medium transition-colors min-w-[44px] min-h-[44px]',
                active
                  ? 'text-primary bg-primary/12'
                  : 'text-muted-foreground hover:text-foreground'
              )}
              aria-label={label}
              aria-current={active ? 'page' : undefined}
              data-testid={`bottom-nav-${label.toLowerCase()}`}
            >
              <Icon size={20} aria-hidden="true" />
              <span>{label}</span>
              {active && (
                <span className="bottom-nav-active-dot" aria-hidden="true" />
              )}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
