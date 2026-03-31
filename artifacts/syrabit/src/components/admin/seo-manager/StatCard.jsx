export default function StatCard({ icon: Icon, label, value, color = '#e8e8e8', sub }) {
  return (
    <div className="rounded-xl p-4 border" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)' }}>
      <Icon size={15} style={{ color, marginBottom: 8 }} />
      <p className="text-2xl font-bold" style={{ color }}>{value ?? '—'}</p>
      <p className="text-[11px] mt-0.5" style={{ color: 'rgba(255,255,255,0.30)' }}>{label}</p>
      {sub && <p className="text-[10px] mt-1" style={{ color: 'rgba(255,255,255,0.20)' }}>{sub}</p>}
    </div>
  );
}
