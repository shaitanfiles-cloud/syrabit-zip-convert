import { useCallback, memo } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { BookOpen, MessageSquare, Clock, User } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { pageImports } from '@/utils/pageImports';
import { prefetchRoute } from '@/utils/prefetchRoute';

const NAV_ITEMS = [
  { to: '/library', icon: BookOpen,      label: 'Browser',  preloadKey: 'library' },
  { to: '/chat',    icon: MessageSquare, label: 'Chat',     preloadKey: 'chat' },
  { to: '/history', icon: Clock,         label: 'History',  preloadKey: 'history' },
  { to: '/profile', icon: User,          label: 'Profile',  preloadKey: 'profile' },
];

export const BottomNav = memo(function BottomNav() {
  const location = useLocation();
  const { user } = useAuth();

  const isActive = (path) =>
    location.pathname === path || location.pathname.startsWith(path + '/');

  const items = NAV_ITEMS;

  const handlePreload = useCallback((preloadKey, to) => {
    if (preloadKey && pageImports[preloadKey]) {
      pageImports[preloadKey]();
    }
    if (to) prefetchRoute(to);
  }, []);

  return (
    <nav
      className="md:hidden fixed bottom-0 left-0 right-0 z-50"
      role="navigation"
      aria-label="Mobile navigation"
      style={{
        background: 'rgba(5,4,14,0.90)',
        backdropFilter: 'blur(28px) saturate(1.6)',
        WebkitBackdropFilter: 'blur(28px) saturate(1.6)',
        borderTop: '1px solid rgba(139,92,246,0.12)',
        boxShadow: '0 -4px 24px rgba(0,0,0,0.25)',
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
      }}
      data-testid="app-bottom-nav"
    >
      <div className="flex items-center justify-around h-16 px-2">
        {items.map(({ to, icon: Icon, label, preloadKey }) => {
          const active = isActive(to);
          return (
            <Link
              key={to}
              to={to}
              onTouchStart={() => handlePreload(preloadKey, to)}
              onMouseEnter={() => handlePreload(preloadKey, to)}
              onFocus={() => handlePreload(preloadKey, to)}
              className="flex flex-col items-center justify-center gap-1 px-3 py-2 rounded-xl text-xs font-medium transition-all duration-200 min-w-[44px] min-h-[44px] relative"
              style={active ? {
                color: '#a78bfa',
                background: 'rgba(124,58,237,0.14)',
              } : {
                color: 'rgba(255,255,255,0.45)',
              }}
              aria-label={label}
              aria-current={active ? 'page' : undefined}
              data-testid={`bottom-nav-${label.toLowerCase()}`}
            >
              <Icon
                size={20}
                aria-hidden="true"
                style={active ? { filter: 'drop-shadow(0 0 6px rgba(167,139,250,0.7))' } : {}}
              />
              <span style={active ? { color: '#a78bfa' } : {}}>{label}</span>
              {active && (
                <span className="bottom-nav-active-dot" aria-hidden="true" />
              )}
            </Link>
          );
        })}
      </div>
    </nav>
  );
});
