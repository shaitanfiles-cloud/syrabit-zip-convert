import { useMemo } from 'react';

export default function FloatingParticles() {
  const particles = useMemo(
    () =>
      Array.from({ length: 28 }, (_, i) => ({
        id: i,
        x: Math.random() * 100,
        y: Math.random() * 100,
        size: Math.random() * 3 + 1,
        duration: Math.random() * 12 + 10,
        delay: Math.random() * 5,
        opacity: Math.random() * 0.35 + 0.05,
        xDrift: Math.random() * 20 - 10,
      })),
    []
  );

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      <style>{`
        @keyframes particleFloat {
          0%, 100% { transform: translate(0, 0);                       opacity: var(--p-opacity-low); }
          50%      { transform: translate(var(--p-x-drift), -40px);    opacity: var(--p-opacity-high); }
        }
        @media (prefers-reduced-motion: reduce) {
          .particle-anim { display: none !important; }
        }
      `}</style>
      {particles.map((p) => (
        <div
          key={p.id}
          className="absolute rounded-full particle-anim"
          style={{
            left: `${p.x}%`,
            top: `${p.y}%`,
            width: p.size,
            height: p.size,
            background: `rgba(139,92,246,${p.opacity})`,
            animation: `particleFloat ${p.duration}s ease-in-out ${p.delay}s infinite`,
            '--p-x-drift': `${p.xDrift}px`,
            '--p-opacity-low': p.opacity,
            '--p-opacity-high': p.opacity * 2.5,
          }}
        />
      ))}
    </div>
  );
}
