import { useState } from 'react';
import { X } from 'lucide-react';

export default function TagChips({ value, onChange, placeholder }) {
  const [input, setInput] = useState('');
  const tags = value ? value.split(',').map(t => t.trim()).filter(Boolean) : [];
  const addTag = () => {
    if (!input.trim()) return;
    onChange([...tags, input.trim()].join(', '));
    setInput('');
  };
  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-1.5">
        {tags.map((t, i) => (
          <span key={i} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs"
            style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd' }}>
            {t}
            <button onClick={() => onChange(tags.filter((_, idx) => idx !== i).join(', '))}
              className="text-white/40 hover:text-white/70"><X size={10} /></button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && addTag()}
          placeholder={placeholder}
          className="flex-1 h-8 px-3 rounded-lg text-xs text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500" />
        <button onClick={addTag} className="px-2 h-8 rounded-lg text-xs font-semibold"
          style={{ background: 'rgba(139,92,246,0.20)', color: '#c4b5fd' }}>Add</button>
      </div>
    </div>
  );
}
