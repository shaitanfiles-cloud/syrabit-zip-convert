import { Outlet } from 'react-router-dom';
import { Link } from 'react-router-dom';
import { PublicNavbar } from './PublicNavbar';

export const PublicLayout = ({ children }) => {
  return (
    /* Landing pages are always dark regardless of theme toggle */
    <div className="min-h-screen" style={{ background: '#06060e', color: '#fff' }}>
      <PublicNavbar />
      <main className="pt-16">
        {children || <Outlet />}
      </main>
      <footer
        className="py-10 px-4"
        style={{ borderTop: '1px solid rgba(255,255,255,0.06)', background: 'rgba(0,0,0,0.3)' }}
      >
        <div className="max-w-7xl mx-auto">
          <div className="flex flex-col md:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <div
                className="w-7 h-7 rounded-xl flex items-center justify-center"
                style={{ background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)' }}
              >
                <span className="text-white text-xs font-bold">S</span>
              </div>
              <span className="text-white font-bold shimmer-text">Syrabit<span style={{ color: '#a78bfa' }}>.ai</span></span>
            </div>
            <div className="flex items-center gap-4 text-sm" style={{ color: 'rgba(255,255,255,0.4)' }}>
              <Link to="/terms"   className="hover:text-white/70 transition-colors py-2 px-1 min-h-[44px] flex items-center">Terms</Link>
              <Link to="/privacy" className="hover:text-white/70 transition-colors py-2 px-1 min-h-[44px] flex items-center">Privacy</Link>
              <Link to="/pricing" className="hover:text-white/70 transition-colors py-2 px-1 min-h-[44px] flex items-center">Pricing</Link>
            </div>
            <p style={{ color: 'rgba(255,255,255,0.25)', fontSize: '0.75rem' }}>
              &copy; {new Date().getFullYear()} Syrabit.ai. All rights reserved.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
};
