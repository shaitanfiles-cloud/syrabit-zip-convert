import { useEffect, useRef, useState } from 'react';

export function ScrollReveal({ children, className = '', delay = 0, threshold = 0.15 }) {
  const ref = useRef(null);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (mq.matches) {
      setRevealed(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setRevealed(true);
          observer.unobserve(el);
        }
      },
      { threshold }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [threshold]);

  return (
    <div
      ref={ref}
      className={`${revealed ? '' : 'reveal'} ${revealed ? 'reveal revealed' : ''} ${className}`}
      style={delay && revealed ? { animationDelay: `${delay}s` } : undefined}
    >
      {children}
    </div>
  );
}

export function StaggerReveal({ children, className = '', staggerMs = 100, threshold = 0.1 }) {
  const ref = useRef(null);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (mq.matches) {
      setRevealed(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setRevealed(true);
          observer.unobserve(el);
        }
      },
      { threshold }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [threshold]);

  return (
    <div ref={ref} className={className}>
      {Array.isArray(children)
        ? children.map((child, i) => (
            <div
              key={child?.key ?? i}
              className={`reveal ${revealed ? 'revealed' : ''}`}
              style={revealed ? { animationDelay: `${i * staggerMs / 1000}s` } : undefined}
            >
              {child}
            </div>
          ))
        : children}
    </div>
  );
}
