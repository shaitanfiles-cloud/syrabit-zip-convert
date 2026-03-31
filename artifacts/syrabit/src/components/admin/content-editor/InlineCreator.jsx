import { useState, useEffect, useRef } from 'react';
import { Plus, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

export default function InlineCreator({ placeholder, onCreate, icon: Icon, color = 'violet' }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [saving, setSaving] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => { if (open && inputRef.current) inputRef.current.focus(); }, [open]);

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className={`w-full p-3 rounded-xl border-2 border-dashed border-white/10 hover:border-${color}-500/40 text-white/40 hover:text-${color}-400 flex items-center gap-2 text-sm transition-colors`} data-testid={`add-${placeholder.toLowerCase()}`}>
        <Plus size={16} /> Add {placeholder}
      </button>
    );
  }

  const submit = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await onCreate(name.trim(), desc.trim());
      setName(''); setDesc(''); setOpen(false);
    } catch (e) {
      toast.error(e.response?.data?.detail || `Failed to create ${placeholder}`);
    } finally { setSaving(false); }
  };

  return (
    <div className="p-3 rounded-xl border border-white/10 bg-white/[0.02] space-y-2">
      <div className="flex items-center gap-2">
        {Icon && <Icon size={16} className={`text-${color}-400`} />}
        <input
          ref={inputRef}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder={`${placeholder} name...`}
          className="flex-1 h-9 px-3 rounded-lg text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
        />
      </div>
      <input
        value={desc}
        onChange={(e) => setDesc(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
        placeholder="Description (optional)"
        className="w-full h-9 px-3 rounded-lg text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
      />
      <div className="flex gap-2">
        <button onClick={() => { setOpen(false); setName(''); setDesc(''); }} className="flex-1 h-8 rounded-lg bg-white/5 hover:bg-white/10 text-white/60 text-xs">Cancel</button>
        <button onClick={submit} disabled={saving || !name.trim()} className={`flex-1 h-8 rounded-lg bg-${color}-600 hover:bg-${color}-500 text-white text-xs font-medium disabled:opacity-40 flex items-center justify-center gap-1`}>
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
          {saving ? 'Creating...' : 'Create'}
        </button>
      </div>
    </div>
  );
}
