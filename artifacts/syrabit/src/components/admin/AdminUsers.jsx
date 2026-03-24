import { useState, useEffect } from 'react';
import { Loader2, Search, Ban, CheckCircle, Crown, ChevronDown } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { adminGetUsers, adminUpdateUserStatus, adminUpdateUserPlan } from '@/utils/api';
import { toast } from 'sonner';

const PLAN_COLORS = {
  free: 'bg-slate-700 text-slate-300',
  starter: 'bg-violet-700/30 text-violet-300',
  pro: 'bg-amber-700/30 text-amber-300',
};

const STATUS_COLORS = {
  active: 'bg-emerald-700/30 text-emerald-300',
  suspended: 'bg-orange-700/30 text-orange-300',
  banned: 'bg-red-700/30 text-red-300',
};

export default function AdminUsers({ adminToken }) {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  useEffect(() => {
    adminGetUsers(adminToken)
      .then((res) => setUsers(res.data))
      .catch(() => toast.error('Failed to load users'))
      .finally(() => setLoading(false));
  }, [adminToken]);

  const handleStatusChange = async (userId, newStatus) => {
    try {
      await adminUpdateUserStatus(adminToken, userId, newStatus);
      setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, status: newStatus } : u));
      toast.success('Status updated');
    } catch {
      toast.error('Failed to update status');
    }
  };

  const handlePlanChange = async (userId, newPlan) => {
    try {
      await adminUpdateUserPlan(adminToken, userId, newPlan);
      setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, plan: newPlan } : u));
      toast.success('Plan updated');
    } catch {
      toast.error('Failed to update plan');
    }
  };

  const filtered = users.filter(
    (u) => !search || u.name?.toLowerCase().includes(search.toLowerCase()) || u.email?.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) return <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-slate-400" /></div>;

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-slate-200 font-semibold">Users ({users.length})</h2>
        <div className="relative w-60">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <Input
            placeholder="Search users..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 bg-slate-800 border-slate-700 text-white text-sm h-8"
          />
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800">
              <th className="text-left text-slate-500 font-medium px-4 py-3">User</th>
              <th className="text-left text-slate-500 font-medium px-4 py-3">Plan</th>
              <th className="text-left text-slate-500 font-medium px-4 py-3">Status</th>
              <th className="text-left text-slate-500 font-medium px-4 py-3">Credits</th>
              <th className="text-left text-slate-500 font-medium px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((user) => (
              <tr key={user.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                <td className="px-4 py-3">
                  <div>
                    <p className="text-slate-200 font-medium">{user.name}</p>
                    <p className="text-slate-500 text-xs">{user.email}</p>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button className={`text-xs px-2 py-1 rounded-full flex items-center gap-1 ${PLAN_COLORS[user.plan] || PLAN_COLORS.free}`}>
                        <Crown size={10} /> {user.plan}
                        <ChevronDown size={10} />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="bg-slate-900 border-slate-800">
                      {['free', 'starter', 'pro'].map((p) => (
                        <DropdownMenuItem key={p} className="text-slate-300 focus:bg-slate-800" onClick={() => handlePlanChange(user.id, p)}>
                          {p}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-1 rounded-full ${STATUS_COLORS[user.status] || STATUS_COLORS.active}`}>
                    {user.status || 'active'}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className="text-slate-400 text-xs">{user.credits_used || 0} / {user.credits_limit || 0}</span>
                </td>
                <td className="px-4 py-3">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="sm" className="h-7 text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800">
                        Actions <ChevronDown size={10} className="ml-1" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="bg-slate-900 border-slate-800">
                      <DropdownMenuItem className="text-slate-300 focus:bg-slate-800" onClick={() => handleStatusChange(user.id, 'active')}>
                        <CheckCircle size={14} className="mr-2 text-emerald-400" /> Set Active
                      </DropdownMenuItem>
                      <DropdownMenuItem className="text-slate-300 focus:bg-slate-800" onClick={() => handleStatusChange(user.id, 'suspended')}>
                        Set Suspended
                      </DropdownMenuItem>
                      <DropdownMenuItem className="text-red-400 focus:bg-slate-800" onClick={() => handleStatusChange(user.id, 'banned')}>
                        <Ban size={14} className="mr-2" /> Ban User
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
