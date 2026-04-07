import { useState, useEffect } from 'react';
import { Save, Loader2, Settings } from 'lucide-react';
import AdminQuickLinks from './AdminQuickLinks';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { adminGetSettings, adminUpdateSettings } from '@/utils/api';
import { toast } from 'sonner';

export default function AdminSettings({ adminToken, onNavigate }) {
  const [settings, setSettings] = useState({
    registrations_open: true,
    maintenance_mode: false,
    app_name: 'Syrabit.ai',
    tagline: 'AI-Powered AHSEC Exam Prep',
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    adminGetSettings(adminToken)
      .then((res) => setSettings((prev) => ({ ...prev, ...res.data })))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [adminToken]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await adminUpdateSettings(adminToken, settings);
      toast.success('Settings saved');
    } catch {
      toast.error('Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-violet-400/60" /></div>;

  return (
    <div className="p-6 max-w-lg space-y-6">
      <h2 className="text-white/90 font-semibold">App Settings</h2>

      <div className="rounded-2xl p-5 space-y-5" style={{
        background: 'rgba(15,15,30,0.6)',
        border: '1px solid rgba(255,255,255,0.06)',
        backdropFilter: 'blur(12px)',
      }}>
        <div className="space-y-1.5">
          <Label className="text-white/30 text-sm">App Name</Label>
          <Input
            value={settings.app_name}
            onChange={(e) => setSettings((s) => ({ ...s, app_name: e.target.value }))}
            className="bg-white/[0.04] border-white/[0.08] text-white focus:border-violet-500"
          />
        </div>

        <div className="space-y-1.5">
          <Label className="text-white/30 text-sm">Tagline</Label>
          <Input
            value={settings.tagline}
            onChange={(e) => setSettings((s) => ({ ...s, tagline: e.target.value }))}
            className="bg-white/[0.04] border-white/[0.08] text-white focus:border-violet-500"
          />
        </div>

        <div className="flex items-center justify-between py-3" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <div>
            <p className="text-white/60 text-sm font-medium">Registrations Open</p>
            <p className="text-white/25 text-xs">Allow new users to sign up</p>
          </div>
          <Switch
            checked={settings.registrations_open}
            onCheckedChange={(v) => setSettings((s) => ({ ...s, registrations_open: v }))}
          />
        </div>

        <div className="flex items-center justify-between py-3" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <div>
            <p className="text-white/60 text-sm font-medium">Maintenance Mode</p>
            <p className="text-white/25 text-xs">Show maintenance page to students</p>
          </div>
          <Switch
            checked={settings.maintenance_mode}
            onCheckedChange={(v) => setSettings((s) => ({ ...s, maintenance_mode: v }))}
          />
        </div>
      </div>

      <Button
        onClick={handleSave}
        disabled={saving}
        className="text-white border-0 transition-all hover:opacity-90"
        style={{ background: 'linear-gradient(135deg, #7c3aed, #6d28d9)', boxShadow: '0 2px 12px rgba(124,58,237,0.3)' }}
      >
        {saving ? <Loader2 size={16} className="animate-spin mr-2" /> : <Save size={16} className="mr-2" />}
        Save Settings
      </Button>
      <AdminQuickLinks links={['apiconfig','googleauth','health','ratelimits']} onNavigate={onNavigate} />
    </div>
  );
}
