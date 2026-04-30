import { useState, useEffect, useMemo } from 'react';

const STEP_DELAYS_MS = [0, 1200, 2500, 3600];

const PULSE_STYLE = `
@keyframes syra-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.35; transform: scale(0.6); }
}
`;

export function ThinkingIndicator({ subject, scopedChapters = [] }) {
  const [activeStep, setActiveStep] = useState(0);
  const [elapsed, setElapsed]       = useState(0);
  const [chapterIdx, setChapterIdx] = useState(0);

  const sortedChapters = useMemo(
    () =>
      [...(scopedChapters || [])].sort(
        (a, b) => (a.order_index ?? a.order ?? 0) - (b.order_index ?? b.order ?? 0),
      ),
    [scopedChapters],
  );

  const steps = useMemo(() => {
    const classLine = [subject?.class_name, subject?.stream_name]
      .filter(Boolean)
      .join(' \u00b7 ');

    return [
      { icon: '🔍', label: 'Searching Assam Board syllabus' },
      { icon: '📚', label: classLine || 'Assam Board curriculum' },
      { icon: '📖', label: subject?.name || 'Your subject' },
      { icon: '📄', label: null },
    ];
  }, [subject]);

  const chapterLabel = useMemo(() => {
    if (!sortedChapters.length) return 'Finding relevant chapter…';
    const ch  = sortedChapters[chapterIdx];
    const num = ch.chapter_number ?? ch.order_index ?? chapterIdx + 1;
    return `Chapter\u00a0${num}\u00a0\u2014\u00a0${ch.title}`;
  }, [sortedChapters, chapterIdx]);

  useEffect(() => {
    const timers = STEP_DELAYS_MS.slice(1).map((delay, i) =>
      setTimeout(() => setActiveStep(i + 1), delay),
    );
    const sec = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => {
      timers.forEach(clearTimeout);
      clearInterval(sec);
    };
  }, []);

  useEffect(() => {
    if (sortedChapters.length < 2) return;
    const t = setInterval(
      () => setChapterIdx((i) => (i + 1) % sortedChapters.length),
      2000,
    );
    return () => clearInterval(t);
  }, [sortedChapters]);

  const progress = Math.min(100, (elapsed / 5) * 100);

  return (
    <>
      <style>{PULSE_STYLE}</style>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '8px 0' }}>
        {steps.map((step, i) => {
          const visible  = i <= activeStep;
          const isActive = i === activeStep;
          const label    = i === 3 ? chapterLabel : step.label;

          return (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                opacity: visible ? (isActive ? 1 : 0.5) : 0,
                transform: visible ? 'translateY(0)' : 'translateY(5px)',
                transition: 'opacity 0.4s ease, transform 0.4s ease',
                pointerEvents: 'none',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  width: 20,
                  flexShrink: 0,
                }}
              >
                {i > 0 && (
                  <div
                    style={{
                      width: 1,
                      height: 6,
                      marginBottom: 2,
                      background: visible ? 'rgba(124,58,237,0.25)' : 'transparent',
                      transition: 'background 0.4s ease',
                    }}
                  />
                )}
                <span style={{ fontSize: 13, lineHeight: 1 }}>{step.icon}</span>
              </div>

              <span
                style={{
                  fontSize: 12.5,
                  lineHeight: '18px',
                  color: isActive ? '#5b21b6' : '#6b7280',
                  fontWeight: isActive ? 600 : 400,
                  letterSpacing: '0.01em',
                  transition: 'color 0.3s ease, font-weight 0.3s ease',
                  flex: 1,
                  minWidth: 0,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {label}
                {isActive && (
                  <span style={{ opacity: 0.6, marginLeft: 1 }}>…</span>
                )}
              </span>

              {isActive && (
                <span
                  style={{
                    display: 'inline-block',
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: '#7c3aed',
                    flexShrink: 0,
                    animation: 'syra-pulse 1.1s ease-in-out infinite',
                  }}
                />
              )}
            </div>
          );
        })}

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            marginTop: 6,
            paddingLeft: 28,
          }}
        >
          <div
            style={{
              height: 2,
              flex: 1,
              maxWidth: 110,
              borderRadius: 4,
              background: 'rgba(124,58,237,0.10)',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${progress}%`,
                borderRadius: 4,
                background: 'linear-gradient(90deg,#7c3aed,#a78bfa)',
                transition: 'width 1s linear',
              }}
            />
          </div>
          <span style={{ fontSize: 11, color: '#9ca3af' }}>{elapsed}s</span>
        </div>
      </div>
    </>
  );
}
