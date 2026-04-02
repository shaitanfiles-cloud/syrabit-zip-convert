import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { GraduationCap, ExternalLink, BookOpen, ArrowLeft, Clock, Share2, MousePointer2 } from 'lucide-react';
import { LogoMark } from '@/components/Logo';

const STUDENT_MESSAGE = 'Explain the photoelectric effect and Einstein\'s equation';
const AI_SHORT_ANSWER = 'The photoelectric effect is the emission of electrons from a metal surface when light of sufficient frequency strikes it.';

const TYPING_SPEED = 35;
const THINKING_DURATION = 3000;
const CLICK_DELAY = 2500;
const LOOP_PAUSE = 5000;
const FADE_DURATION = 600;

const CLICKING_DURATION = 800;

const PHASES = {
  IDLE: 'idle',
  TYPING: 'typing',
  THINKING: 'thinking',
  SHORT_ANSWER: 'short_answer',
  CLICKING: 'clicking',
  PAGE_VIEW: 'page_view',
  COMPLETE: 'complete',
  FADING: 'fading',
};

function TypingCursor() {
  return (
    <motion.span
      className="inline-block w-0.5 h-3.5 ml-0.5 align-middle"
      style={{ background: 'rgba(255,255,255,0.60)' }}
      animate={{ opacity: [1, 0] }}
      transition={{ duration: 0.6, repeat: Infinity, repeatType: 'reverse' }}
    />
  );
}

function ThinkingIndicator() {
  return (
    <div className="space-y-2 py-1" style={{ width: '100%', maxWidth: 180 }}>
      <div className="flex items-center gap-1.5 mb-2">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: '#a78bfa' }}
            animate={{ opacity: [0.3, 1, 0.3] }}
            transition={{ duration: 0.8, repeat: Infinity, delay: i * 0.15, ease: 'easeInOut' }}
          />
        ))}
        <span className="text-xs ml-1" style={{ color: 'rgba(255,255,255,0.60)' }}>Thinking</span>
      </div>
      {[1, 0.7, 0.4].map((widthFrac, i) => (
        <motion.div
          key={i}
          className="rounded"
          style={{
            height: 8,
            width: `${widthFrac * 100}%`,
            background: 'linear-gradient(90deg, rgba(139,92,246,0.08) 25%, rgba(139,92,246,0.18) 50%, rgba(139,92,246,0.08) 75%)',
            backgroundSize: '200% 100%',
          }}
          animate={{ backgroundPosition: ['200% 0', '-200% 0'] }}
          transition={{ duration: 1.5, repeat: Infinity, ease: 'linear', delay: i * 0.15 }}
        />
      ))}
    </div>
  );
}

function SourceBadge({ pulsing, clicking }) {
  return (
    <motion.div
      className="relative flex items-center gap-1.5 mt-2"
      animate={
        clicking
          ? { scale: [1, 0.92, 1.02, 1] }
          : pulsing
          ? { scale: [1, 1.05, 1] }
          : {}
      }
      transition={
        clicking
          ? { duration: 0.35, ease: 'easeInOut' }
          : pulsing
          ? { duration: 0.8, repeat: 2 }
          : {}
      }
    >
      <span
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full relative overflow-hidden"
        style={{
          fontSize: 12,
          background: clicking ? 'rgba(139,92,246,0.45)' : 'rgba(139,92,246,0.20)',
          color: '#a78bfa',
          border: clicking ? '1px solid rgba(139,92,246,0.50)' : '1px solid rgba(139,92,246,0.22)',
          transition: 'background 0.2s, border 0.2s',
          boxShadow: clicking ? '0 0 12px rgba(139,92,246,0.4)' : 'none',
        }}
      >
        <BookOpen size={9} />
        Chapter 11 · Wave Optics
        {clicking && (
          <motion.span
            className="absolute inset-0 rounded-full"
            initial={{ scale: 0, opacity: 0.6 }}
            animate={{ scale: 2.5, opacity: 0 }}
            transition={{ duration: 0.5 }}
            style={{ background: 'rgba(167,139,250,0.4)', transformOrigin: 'center' }}
          />
        )}
      </span>
      <ExternalLink size={10} style={{ color: '#a78bfa', opacity: 0.7 }} />

      {clicking && (
        <motion.div
          className="absolute"
          initial={{ x: -30, y: -20, opacity: 0 }}
          animate={{ x: 4, y: 4, opacity: 1 }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
          style={{ zIndex: 10, left: 0, top: 0 }}
        >
          <MousePointer2 size={14} style={{ color: 'white', filter: 'drop-shadow(0 1px 3px rgba(0,0,0,0.5))' }} />
        </motion.div>
      )}
    </motion.div>
  );
}

function ContentPageView() {
  return (
    <div className="p-5 space-y-4">
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.1, duration: 0.3 }}
        className="flex items-center gap-2"
      >
        <ArrowLeft size={14} style={{ color: 'rgba(255,255,255,0.60)' }} />
        <span className="text-xs" style={{ color: 'rgba(255,255,255,0.60)' }}>Back to chat</span>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15, duration: 0.35 }}
        className="flex items-start justify-between"
      >
        <div>
          <h3 className="text-sm font-bold text-white mb-1">Photoelectric Effect</h3>
          <p className="text-xs" style={{ color: 'rgba(255,255,255,0.60)' }}>AHSEC Class 12 · Physics · Chapter 11</p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full"
            style={{ fontSize: 12, background: 'rgba(34,197,94,0.12)', color: 'rgba(34,197,94,0.7)', border: '1px solid rgba(34,197,94,0.15)' }}
          >
            AHSEC Syllabus
          </span>
          <Share2 size={11} style={{ color: 'rgba(255,255,255,0.60)' }} />
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.25, duration: 0.3 }}
        style={{ height: 1, background: 'rgba(255,255,255,0.06)' }}
      />

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3, duration: 0.35 }}
      >
        <p className="text-xs leading-relaxed mb-3" style={{ color: 'rgba(255,255,255,0.65)' }}>
          The photoelectric effect occurs when electromagnetic radiation (light) of sufficient frequency strikes a metallic surface, causing the emission of electrons. This phenomenon was first explained by Albert Einstein in 1905 using the quantum theory of light.
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.45, duration: 0.35 }}
        className="rounded-lg p-3"
        style={{ background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.12)' }}
      >
        <p className="text-xs font-semibold mb-2" style={{ color: 'rgba(255,255,255,0.60)' }}>Einstein's Photoelectric Equation</p>
        <code
          className="text-sm font-mono block text-center py-1"
          style={{ color: '#c4b5fd' }}
        >
          E = hν = φ + ½mv²
        </code>
        <div className="mt-2 space-y-0.5">
          <p className="text-xs" style={{ color: 'rgba(255,255,255,0.60)' }}><span style={{ color: '#a78bfa' }}>E</span> = energy of incident photon</p>
          <p className="text-xs" style={{ color: 'rgba(255,255,255,0.60)' }}><span style={{ color: '#a78bfa' }}>h</span> = Planck's constant (6.626 × 10⁻³⁴ J·s)</p>
          <p className="text-xs" style={{ color: 'rgba(255,255,255,0.60)' }}><span style={{ color: '#a78bfa' }}>ν</span> = frequency of incident light</p>
          <p className="text-xs" style={{ color: 'rgba(255,255,255,0.60)' }}><span style={{ color: '#a78bfa' }}>φ</span> = work function of the metal</p>
          <p className="text-xs" style={{ color: 'rgba(255,255,255,0.60)' }}><span style={{ color: '#a78bfa' }}>½mv²</span> = max kinetic energy of photoelectron</p>
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.6, duration: 0.3 }}
        className="flex items-center gap-3 pt-1"
      >
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full"
          style={{ fontSize: 12, background: 'rgba(139,92,246,0.15)', color: '#a78bfa', border: '1px solid rgba(139,92,246,0.18)' }}
        >
          <Clock size={10} />
          2 credits used
        </span>
        <span
          className="px-2 py-0.5 rounded-full"
          style={{ fontSize: 12, background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.60)', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          Wave Optics
        </span>
        <span
          className="px-2 py-0.5 rounded-full"
          style={{ fontSize: 12, background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.60)', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          Quantum Theory
        </span>
      </motion.div>
    </div>
  );
}

const fadeSlide = {
  hidden: { opacity: 0, y: 10 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.35, ease: 'easeOut' } },
};

export default function AnimatedChatDemo({ onUrlChange }) {
  const [phase, setPhase] = useState(PHASES.IDLE);
  const [typedCount, setTypedCount] = useState(0);
  const [shortAnswerTyped, setShortAnswerTyped] = useState(0);
  const [containerOpacity, setContainerOpacity] = useState(1);
  const [isInView, setIsInView] = useState(false);
  const containerRef = useRef(null);
  const timeoutRef = useRef(null);
  const intervalRef = useRef(null);

  const clearTimers = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    if (intervalRef.current) clearInterval(intervalRef.current);
  }, []);

  const resetState = useCallback(() => {
    clearTimers();
    setPhase(PHASES.IDLE);
    setTypedCount(0);
    setShortAnswerTyped(0);
    setContainerOpacity(1);
    onUrlChange?.('chat');
  }, [clearTimers, onUrlChange]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => setIsInView(entry.isIntersecting),
      { threshold: 0.3 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (isInView && phase === PHASES.IDLE) {
      timeoutRef.current = setTimeout(() => setPhase(PHASES.TYPING), 800);
    }
    if (!isInView && phase !== PHASES.IDLE) {
      resetState();
    }
    return () => { if (timeoutRef.current) clearTimeout(timeoutRef.current); };
  }, [isInView, phase, resetState]);

  useEffect(() => {
    if (phase !== PHASES.TYPING) return;
    intervalRef.current = setInterval(() => {
      setTypedCount((prev) => {
        if (prev >= STUDENT_MESSAGE.length) {
          clearInterval(intervalRef.current);
          timeoutRef.current = setTimeout(() => setPhase(PHASES.THINKING), 400);
          return prev;
        }
        return prev + 1;
      });
    }, TYPING_SPEED);
    return () => clearInterval(intervalRef.current);
  }, [phase]);

  useEffect(() => {
    if (phase !== PHASES.THINKING) return;
    timeoutRef.current = setTimeout(() => setPhase(PHASES.SHORT_ANSWER), THINKING_DURATION);
    return () => clearTimeout(timeoutRef.current);
  }, [phase]);

  useEffect(() => {
    if (phase !== PHASES.SHORT_ANSWER) return;
    intervalRef.current = setInterval(() => {
      setShortAnswerTyped((prev) => {
        if (prev >= AI_SHORT_ANSWER.length) {
          clearInterval(intervalRef.current);
          timeoutRef.current = setTimeout(() => {
            setPhase(PHASES.CLICKING);
          }, CLICK_DELAY);
          return prev;
        }
        return prev + 2;
      });
    }, 18);
    return () => { clearInterval(intervalRef.current); if (timeoutRef.current) clearTimeout(timeoutRef.current); };
  }, [phase, onUrlChange]);

  useEffect(() => {
    if (phase !== PHASES.CLICKING) return;
    timeoutRef.current = setTimeout(() => {
      onUrlChange?.('library');
      setPhase(PHASES.PAGE_VIEW);
    }, CLICKING_DURATION);
    return () => clearTimeout(timeoutRef.current);
  }, [phase, onUrlChange]);

  useEffect(() => {
    if (phase !== PHASES.PAGE_VIEW) return;
    timeoutRef.current = setTimeout(() => setPhase(PHASES.COMPLETE), 400);
    return () => clearTimeout(timeoutRef.current);
  }, [phase]);

  useEffect(() => {
    if (phase !== PHASES.COMPLETE) return;
    timeoutRef.current = setTimeout(() => {
      setPhase(PHASES.FADING);
      setContainerOpacity(0);
      timeoutRef.current = setTimeout(() => resetState(), FADE_DURATION);
    }, LOOP_PAUSE);
    return () => clearTimeout(timeoutRef.current);
  }, [phase, resetState]);

  const showStudent = phase !== PHASES.IDLE && phase !== PHASES.PAGE_VIEW && phase !== PHASES.COMPLETE && phase !== PHASES.FADING;
  const showThinking = phase === PHASES.THINKING;
  const showShortAnswer = phase === PHASES.SHORT_ANSWER;
  const showPageView = phase === PHASES.PAGE_VIEW || phase === PHASES.COMPLETE || phase === PHASES.FADING;

  const showClicking = phase === PHASES.CLICKING;

  const aiBubbleStyle = {
    background: 'linear-gradient(135deg,rgba(124,58,237,0.22),rgba(109,40,217,0.16))',
    border: '1px solid rgba(139,92,246,0.22)',
    borderRadius: '0 1rem 1rem 1rem',
  };

  return (
    <div
      ref={containerRef}
      style={{ minHeight: 200, transition: `opacity ${FADE_DURATION}ms ease`, opacity: containerOpacity }}
    >
      <AnimatePresence mode="wait">
        {!showPageView ? (
          <motion.div
            key="chat-view"
            initial={{ opacity: 1 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.3 }}
            className="p-6 text-left space-y-4"
          >
            <AnimatePresence>
              {showStudent && (
                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="flex items-start gap-3 flex-row-reverse"
                >
                  <div
                    className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center"
                    style={{ background: 'rgba(124,58,237,0.20)', border: '1px solid rgba(139,92,246,0.30)' }}
                  >
                    <GraduationCap size={14} className="text-violet-400" />
                  </div>
                  <div
                    className="px-4 py-3 text-sm max-w-xs"
                    style={{ background: 'rgba(255,255,255,0.06)', borderRadius: '1rem 0 1rem 1rem', color: 'rgba(255,255,255,0.80)' }}
                  >
                    {STUDENT_MESSAGE.slice(0, typedCount)}
                    {phase === PHASES.TYPING && <TypingCursor />}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <AnimatePresence>
              {showThinking && (
                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.25 }}
                  className="flex items-start gap-3"
                >
                  <div
                    className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center"
                    style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)' }}
                  >
                    <LogoMark size="xs" style={{ filter: 'none' }} />
                  </div>
                  <div className="px-4 py-3 text-sm max-w-sm" style={aiBubbleStyle}>
                    <ThinkingIndicator />
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <AnimatePresence>
              {(showShortAnswer || showClicking) && (
                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="flex items-start gap-3"
                >
                  <div
                    className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center"
                    style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)' }}
                  >
                    <LogoMark size="xs" style={{ filter: 'none' }} />
                  </div>
                  <div className="px-4 py-3 text-sm max-w-sm" style={aiBubbleStyle}>
                    <p className="text-xs leading-relaxed" style={{ color: 'rgba(255,255,255,0.78)' }}>
                      {AI_SHORT_ANSWER.slice(0, shortAnswerTyped)}
                      {shortAnswerTyped < AI_SHORT_ANSWER.length && <TypingCursor />}
                    </p>
                    <AnimatePresence>
                      {shortAnswerTyped >= AI_SHORT_ANSWER.length && (
                        <motion.div variants={fadeSlide} initial="hidden" animate="visible">
                          <SourceBadge pulsing={showShortAnswer} clicking={showClicking} />
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        ) : (
          <motion.div
            key="page-view"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
          >
            <ContentPageView />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
