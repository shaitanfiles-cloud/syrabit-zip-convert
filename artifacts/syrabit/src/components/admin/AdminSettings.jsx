import { useState, useEffect } from 'react';
import { Save, Loader2, Settings } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { adminGetSettings, adminUpdateSettings } from '@/utils/api';
import { toast } from 'sonner';

export default function AdminSettings({ adminToken }) {
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

  if (loading) return <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-slate-400" /></div>;

  return (
    <div className="p-6 max-w-lg space-y-6">
      <h2 className="text-slate-200 font-semibold">App Settings</h2>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-5">
        <div className="space-y-1.5">
          <Label className="text-slate-400 text-sm">App Name</Label>
          <Input
            value={settings.app_name}
            onChange={(e) => setSettings((s) => ({ ...s, app_name: e.target.value }))}
            className="bg-slate-800 border-slate-700 text-white"
          />
        </div>

        <div className="space-y-1.5">
          <Label className="text-slate-400 text-sm">Tagline</Label>
          <Input
            value={settings.tagline}
            onChange={(e) => setSettings((s) => ({ ...s, tagline: e.target.value }))}
            className="bg-slate-800 border-slate-700 text-white"
          />
        </div>

        <div className="flex items-center justify-between py-3 border-t border-slate-800">
          <div>
            <p className="text-slate-300 text-sm font-medium">Registrations Open</p>
            <p className="text-slate-500 text-xs">Allow new users to sign up</p>
          </div>
          <Switch
            checked={settings.registrations_open}
            onCheckedChange={(v) => setSettings((s) => ({ ...s, registrations_open: v }))}
          />
        </div>

        <div className="flex items-center justify-between py-3 border-t border-slate-800">
          <div>
            <p className="text-slate-300 text-sm font-medium">Maintenance Mode</p>
            <p className="text-slate-500 text-xs">Show maintenance page to students</p>
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
        className="bg-slate-700 hover:bg-slate-600 text-white"
      >
        {saving ? <Loader2 size={16} className="animate-spin mr-2" /> : <Save size={16} className="mr-2" />}
        Save Settings
      </Button>
    </div>
  );
}
