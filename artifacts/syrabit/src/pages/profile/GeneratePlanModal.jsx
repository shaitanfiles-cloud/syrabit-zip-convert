import { X, Sparkles, Loader2 } from 'lucide-react';

export default function GeneratePlanModal({
  showGenModal, genForm, setGenForm,
  genLoading, handleGeneratePlan, setShowGenModal,
}) {
  if (!showGenModal) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) setShowGenModal(false); }}>
      <div
        className="relative w-full max-w-md rounded-2xl overflow-hidden"
        style={{ background: 'var(--card)', border: '1px solid rgba(139,92,246,0.25)', boxShadow: '0 24px 80px rgba(0,0,0,0.5)' }}>
        <div className="flex items-center justify-between px-5 pt-5 pb-4"
          style={{ borderBottom: '1px solid rgba(139,92,246,0.10)' }}>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl flex items-center justify-center" style={{ background: 'rgba(139,92,246,0.15)' }}>
              <Sparkles size={15} className="text-violet-400" />
            </div>
            <span className="text-sm font-bold text-white">Generate My Study Plan</span>
          </div>
          <button onClick={() => setShowGenModal(false)} className="p-1.5 rounded-lg hover:bg-white/8 transition-colors">
            <X size={16} className="text-white/50" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div>
            <label className="text-xs font-medium text-white/60 block mb-1.5">Subject</label>
            <input
              type="text"
              value={genForm.subject_name}
              onChange={e => setGenForm(f => ({ ...f, subject_name: e.target.value }))}
              placeholder="e.g. Physics, Chemistry, English"
              className="w-full h-10 px-3 rounded-xl text-sm bg-white/5 border border-white/10 text-white placeholder:text-white/30 focus:outline-none focus:border-violet-500/50"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-white/60 block mb-1.5">What are you weak in?</label>
            <textarea
              rows={3}
              value={genForm.context}
              onChange={e => setGenForm(f => ({ ...f, context: e.target.value }))}
              placeholder="e.g. I struggle with Motion, Gravitation, and Optics."
              className="w-full px-3 py-2 rounded-xl text-sm bg-white/5 border border-white/10 text-white placeholder:text-white/30 focus:outline-none focus:border-violet-500/50 resize-none"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-white/60 block mb-1.5">Sprint length (days)</label>
            <div className="flex gap-2">
              {[3, 5, 7, 14].map(d => (
                <button key={d}
                  onClick={() => setGenForm(f => ({ ...f, days: d }))}
                  className={`flex-1 h-9 rounded-xl text-sm font-semibold border transition-all ${genForm.days === d
                    ? 'text-white border-violet-500/60'
                    : 'text-white/40 border-white/10 hover:border-white/20'}`}
                  style={genForm.days === d ? { background: 'rgba(124,58,237,0.20)' } : {}}>
                  {d}d
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={handleGeneratePlan}
            disabled={genLoading}
            className="w-full h-11 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 disabled:opacity-60 hover:opacity-90 transition-all"
            style={{ background: 'linear-gradient(135deg,#7c3aed,#6d28d9)', boxShadow: '0 4px 20px rgba(124,58,237,0.35)' }}>
            {genLoading ? <><Loader2 size={15} className="animate-spin" /> Generating plan…</> : <><Sparkles size={15} /> Generate My {genForm.days}-Day Plan</>}
          </button>
          <p className="text-center text-[11px] text-white/30">Your plan is private — only you can see it</p>
        </div>
      </div>
    </div>
  );
}
