import { motion } from 'framer-motion';
import { BookOpen, Users, TrendingUp } from 'lucide-react';
import AnimatedStat from './AnimatedStat';
import AnimatedChatDemo from './AnimatedChatDemo';
import { fadeUp, staggerContainer } from './shared';
import { usePublicStats } from '@/hooks/usePublicStats';

const _statLabels = {
  en: { divisions: 'AssamBoard Divisions', students: 'Students', plans: 'Plans' },
  as: { divisions: 'অসম বোৰ্ড বিভাগ', students: 'ছাত্ৰ-ছাত্ৰী', plans: 'পৰিকল্পনা' },
};

export default function HeroBelowFold({ contentLang = 'en', browserPath, onUrlChange }) {
  const publicStats = usePublicStats();
  const userCount = publicStats?.total_users || 100;
  const labels = _statLabels[contentLang] || _statLabels.en;

  const stats = [
    { value: '3',             label: labels.divisions, icon: BookOpen   },
    { value: `${userCount}+`, label: labels.students,  icon: Users      },
    { value: '3',             label: labels.plans,     icon: TrendingUp },
  ];

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 48, scale: 0.94 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 1, ease: [0.16, 1, 0.3, 1], delay: 0.2 }}
        className="mt-16 relative max-w-3xl mx-auto"
      >
        <div
          className="absolute -inset-4 rounded-3xl pointer-events-none"
          style={{ background: 'rgba(124,58,237,0.08)', filter: 'blur(60px)' }}
        />
        <div
          className="relative rounded-3xl overflow-hidden"
          style={{
            border: '1px solid rgba(139,92,246,0.15)',
            background: 'linear-gradient(135deg, rgba(15,10,30,0.95) 0%, rgba(20,15,40,0.98) 100%)',
            boxShadow: '0 32px 80px rgba(0,0,0,0.25), 0 0 0 1px rgba(139,92,246,0.08)',
          }}
        >
          <div
            className="flex items-center gap-2 px-4 py-3 border-b"
            style={{ borderColor: 'rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.02)' }}
          >
            <span className="w-3 h-3 rounded-full" style={{ background: 'rgba(239,68,68,0.6)' }} />
            <span className="w-3 h-3 rounded-full" style={{ background: 'rgba(234,179,8,0.6)' }} />
            <span className="w-3 h-3 rounded-full" style={{ background: 'rgba(34,197,94,0.6)' }} />
            <div
              className="flex-1 mx-4 h-6 rounded-lg flex items-center px-3"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
            >
              <motion.span
                key={browserPath}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.3 }}
                className="text-xs"
                style={{ color: 'rgba(255,255,255,0.60)' }}
              >
                syrabit.ai/{browserPath}
              </motion.span>
            </div>
          </div>

          <AnimatedChatDemo onUrlChange={onUrlChange} contentLang={contentLang} />
        </div>
      </motion.div>

      <section
        className="py-16 mt-16 -mx-5"
        style={{
          background: 'hsl(var(--muted) / 0.3)',
          borderTop: '1px solid hsl(var(--border) / 0.3)',
          borderBottom: '1px solid hsl(var(--border) / 0.3)',
        }}
      >
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
          variants={staggerContainer}
          className="max-w-4xl mx-auto px-5 grid grid-cols-1 sm:grid-cols-3 gap-8"
        >
          {stats.map((s, i) => (
            <motion.div key={s.label} variants={fadeUp(i * 0.07)}>
              <AnimatedStat value={s.value} label={s.label} icon={s.icon} />
            </motion.div>
          ))}
        </motion.div>
      </section>
    </>
  );
}
