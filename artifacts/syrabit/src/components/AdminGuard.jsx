import { Outlet } from 'react-router-dom';

export const AdminGuard = ({ children }) => {
  return children || <Outlet />;
};
