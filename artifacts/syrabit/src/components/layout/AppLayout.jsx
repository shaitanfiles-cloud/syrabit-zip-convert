import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { BottomNav } from './BottomNav';
import { Navbar } from './Navbar';

export function AppLayout(props) {
  const { pageTitle, children } = props;
  return (
    <div className="flex h-screen bg-background futuristic-bg grid-overlay overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header>
          <Navbar pageTitle={pageTitle} />
        </header>
        <main
          id="main-content"
          role="main"
          className="flex-1 overflow-y-auto pb-16 md:pb-0"
          tabIndex={-1}
        >
          {children ? children : <Outlet />}
        </main>
      </div>
      <BottomNav />
    </div>
  );
}
