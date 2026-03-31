import { motion } from 'framer-motion';
import { fadeUp } from './shared';

export default function Reveal({ children, delay = 0, className = '' }) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: '-60px' }}
      variants={fadeUp(delay)}
    >
      {children}
    </motion.div>
  );
}
