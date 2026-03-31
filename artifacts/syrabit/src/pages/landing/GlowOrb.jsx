import { motion, useReducedMotion } from 'framer-motion';

export default function GlowOrb({ color, size, x, y, blur, opacity = 0.18, animRange = 30, duration = 14 }) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className="absolute rounded-full pointer-events-none"
      style={{
        width: size,
        height: size,
        left: x,
        top: y,
        background: color,
        filter: `blur(${blur}px)`,
        opacity,
      }}
      animate={reduced ? {} : {
        x: [0, animRange, -animRange / 2, 0],
        y: [0, -animRange / 2, animRange, 0],
        scale: [1, 1.08, 0.96, 1],
      }}
      transition={{
        duration,
        repeat: Infinity,
        ease: 'easeInOut',
      }}
    />
  );
}
