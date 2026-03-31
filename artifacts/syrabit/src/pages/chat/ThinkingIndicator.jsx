import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const THINKING_STEPS = [
  'Searching in AssamBoard Syllabus…',
  'Reading relevant chapters…',
  'Cross-referencing chapter content…',
  'Verifying accuracy for board exams…',
  'Composing your answer…',
];

export function ThinkingIndicator() {
  const [stepIdx, setStepIdx]   = useState(0);
  const [elapsed, setElapsed]   = useState(0);
  const [dots, setDots]         = useState('');

  useEffect(() => {
    const stepTimer  = setInterval(() => setStepIdx((i) => (i + 1) % THINKING_STEPS.length), 2200);
    const secTimer   = setInterval(() => setElapsed((s) => s + 1), 1000);
    const dotTimer   = setInterval(() => setDots((d) => (d.length >= 3 ? '' : d + '.')), 400);
    return () => { clearInterval(stepTimer); clearInterval(secTimer); clearInterval(dotTimer); };
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {[0, 1, 2].map((i) => (
            <motion.span
              key={i}
              style={{ width: 6, height: 6, borderRadius: '50%', background: '#7c3aed', display: 'block' }}
              animate={{ y: [0, -5, 0], opacity: [0.4, 1, 0.4] }}
              transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.18, ease: 'easeInOut' }}
            />
          ))}
        </div>
        <AnimatePresence mode="wait">
          <motion.span
            key={stepIdx}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.3 }}
            style={{ fontSize: 13, color: 'var(--muted-foreground)', fontStyle: 'italic' }}
          >
            {THINKING_STEPS[stepIdx]}{dots}
          </motion.span>
        </AnimatePresence>
      </div>
      {elapsed > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 2 }}>
          <div style={{ height: 2, flex: 1, maxWidth: 140, borderRadius: 4, background: 'rgba(124,58,237,0.12)', overflow: 'hidden' }}>
            <motion.div
              style={{ height: '100%', borderRadius: 4, background: 'linear-gradient(90deg,#7c3aed,#a78bfa)' }}
              animate={{ x: ['-100%', '200%'] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
            />
          </div>
          <span style={{ fontSize: 11, color: 'var(--muted-foreground)', opacity: 0.55 }}>
            {elapsed}s
          </span>
        </div>
      )}
    </div>
  );
}
