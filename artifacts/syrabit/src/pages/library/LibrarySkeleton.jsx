export default function LibrarySkeleton() {
  const pulse = { background: 'rgba(255,255,255,0.06)' };
  const pulseDim = { background: 'rgba(255,255,255,0.04)' };
  return (
    <div className="flex flex-col h-full w-full overflow-hidden animate-pulse">
      <div className="shrink-0 w-full" style={{ borderBottom: '1px solid rgba(139,92,246,0.08)' }}>
        <div className="w-full max-w-6xl mx-auto px-4 md:px-6 pt-5 pb-3 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-2">
              <div className="h-6 w-48 rounded-lg" style={pulse} />
              <div className="h-3 w-32 rounded" style={pulseDim} />
            </div>
            <div className="h-9 w-24 rounded-xl" style={pulse} />
          </div>
          <div className="h-11 w-full rounded-xl" style={pulseDim} />
          <div className="flex gap-2.5">
            <div className="h-9 flex-1 rounded-xl" style={pulseDim} />
            <div className="h-9 flex-1 rounded-xl" style={pulseDim} />
          </div>
          <div className="flex gap-2">
            {[60, 80, 72, 68, 90].map((w) => (
              <div key={w} className="h-8 rounded-full flex-shrink-0" style={{ width: w, ...pulseDim }} />
            ))}
          </div>
        </div>
      </div>
      <div className="flex-1 overflow-hidden">
        <div className="w-full max-w-6xl mx-auto px-4 md:px-6 py-5">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
            {[...Array(6)].map((_, i) => (
              <div
                key={i}
                className="rounded-2xl border"
                style={{ background: 'rgba(255,255,255,0.03)', borderColor: 'rgba(139,92,246,0.07)' }}
              >
                <div className="h-9 rounded-t-2xl" style={pulseDim} />
                <div className="p-3 space-y-2.5">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl flex-shrink-0" style={pulse} />
                    <div className="flex-1 space-y-1.5">
                      <div className="h-4 rounded w-3/4" style={pulse} />
                      <div className="h-3 rounded w-1/2" style={pulseDim} />
                    </div>
                  </div>
                  <div className="h-3 rounded w-full" style={pulseDim} />
                  <div className="space-y-1.5">
                    {[...Array(3)].map((_, j) => (
                      <div key={j} className="h-9 rounded-lg" style={pulseDim} />
                    ))}
                  </div>
                  <div className="grid grid-cols-2 gap-1.5 pt-1">
                    {[...Array(4)].map((_, j) => (
                      <div key={j} className="h-10 rounded-lg" style={pulseDim} />
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
