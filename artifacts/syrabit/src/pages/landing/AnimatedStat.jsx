import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';

export default function AnimatedStat({ value, label, icon: Icon }) {
  const [display, setDisplay] = useState('0');
  const ref = useRef(null);
  const animated = useRef(false);

  useEffect(() => {
    const strValue = String(value);
    const numeric = parseInt(strValue, 10);
    const suffix = strValue.replace(String(numeric), '');
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !animated.current) {
        animated.current = true;
        const duration = 1200;
        const steps = Math.min(numeric, 60);
        const intervalMs = duration / steps;
        const increment = Math.max(1, Math.ceil(numeric / steps));
        let current = 0;
        const timer = setInterval(() => {
          current = Math.min(current + increment, numeric);
          setDisplay(String(current) + suffix);
          if (current >= numeric) clearInterval(timer);
        }, intervalMs);
      }
    }, { threshold: 0.5 });
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [value]);

  return (
    <div ref={ref} className="flex flex-col items-center gap-2">
      <motion.div
        whileHover={{ scale: 1.08 }}
        className="w-12 h-12 rounded-2xl flex items-center justify-center mb-1"
        style={{
          background: 'rgba(124,58,237,0.08)',
          border: '1px solid rgba(139,92,246,0.18)',
          boxShadow: '0 0 20px rgba(139,92,246,0.08)',
        }}
      >
        <Icon className="w-5 h-5 text-violet-600" />
      </motion.div>
      <span className="text-foreground" style={{ fontSize: '2rem', fontWeight: 800 }}>{display}</span>
      <span className="text-muted-foreground text-sm">{label}</span>
    </div>
  );
}
