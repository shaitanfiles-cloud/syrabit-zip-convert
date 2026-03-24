import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronRight, ChevronLeft, Globe, BookOpen, GraduationCap, FlaskConical, Leaf, Feather, Loader2, Sparkles, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/context/AuthContext';
import { getBoards, getClasses, getStreams, saveOnboarding } from '@/utils/api';
import { toast } from 'sonner';
import { Toaster } from '@/components/ui/sonner';
import { LogoMark } from '@/components/Logo';

const STEPS = ['Board', 'Class', 'Stream'];

const STREAM_ICONS = {
  'Science (PCM)': FlaskConical,
  'Science (PCB)': Leaf,
  'Arts': Feather,
  'B.Com': Feather,
  'B.A': BookOpen,
  'B.Sc': FlaskConical,
};

const STREAM_COLORS = {
  'Science (PCM)': 'from-cyan-500/20 to-blue-500/20 border-cyan-500/30',
  'Science (PCB)': 'from-emerald-500/20 to-green-500/20 border-emerald-500/30',
  'Arts':          'from-amber-500/20 to-orange-500/20 border-amber-500/30',
  'B.Com':         'from-amber-500/20 to-yellow-500/20 border-amber-500/30',
  'B.A':           'from-rose-500/20 to-pink-500/20 border-rose-500/30',
  'B.Sc':          'from-cyan-500/20 to-teal-500/20 border-cyan-500/30',
};

export default function OnboardingPage() {
  const navigate = useNavigate();
  const { user, refreshUser } = useAuth();
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState(1);

  const [boards, setBoards] = useState([]);
  const [classes, setClasses] = useState([]);
  const [streams, setStreams] = useState([]);

  const [selectedBoard, setSelectedBoard] = useState(null);
  const [selectedClass, setSelectedClass] = useState(null);
  const [selectedStream, setSelectedStream] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!user) navigate('/login');
    if (user?.onboarding_done) navigate('/library');
  }, [user, navigate]);

  useEffect(() => {
    getBoards().then((res) => setBoards(res.data));
  }, []);

  useEffect(() => {
    if (selectedBoard) {
      setLoading(true);
      getClasses(selectedBoard.id)
        .then((res) => setClasses(res.data))
        .finally(() => setLoading(false));
    }
  }, [selectedBoard]);

  useEffect(() => {
    if (selectedClass) {
      setLoading(true);
      getStreams(selectedClass.id)
        .then((res) => setStreams(res.data))
        .finally(() => setLoading(false));
    }
  }, [selectedClass]);

  const goNext = () => {
    setDirection(1);
    setStep((s) => s + 1);
  };

  const goBack = () => {
    setDirection(-1);
    setStep((s) => s - 1);
  };

  const handleFinish = async () => {
    setSaving(true);
    try {
      const onboardingData = {
        board_id: selectedBoard.id,
        board_name: selectedBoard.name,
        class_id: selectedClass.id,
        class_name: selectedClass.name,
        stream_id: selectedStream.id,
        stream_name: selectedStream.name,
      };
      await saveOnboarding(onboardingData);
      // Persist for getOnboardingProfile() synchronous reads (Library auto-filter)
      localStorage.setItem('syrabit:onboarding', JSON.stringify(onboardingData));
      await refreshUser();
      toast.success('Setup complete! Welcome to Syrabit.ai');
      navigate('/library');
    } catch (err) {
      toast.error('Failed to save preferences');
    } finally {
      setSaving(false);
    }
  };

  const variants = {
    enter: (dir) => ({ x: dir * 48, opacity: 0 }),
    center: { x: 0, opacity: 1 },
    exit: (dir) => ({ x: dir * -48, opacity: 0 }),
  };

  const canGoNext = [
    selectedBoard !== null,
    selectedClass !== null,
    selectedStream !== null,
  ];

  const getStreamIcon = (name) => STREAM_ICONS[name] || FlaskConical;
  const getStreamColor = (name) => STREAM_COLORS[name] || 'from-violet-500/20 to-purple-500/20 border-violet-500/30';

  return (
    <div className="min-h-screen bg-[#06060e] futuristic-bg grid-overlay flex items-center justify-center p-4">
      <Toaster richColors position="top-right" />
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="flex justify-center mb-4">
            <LogoMark size="xl" className="anim-float" />
          </div>
          <h1 className="text-2xl font-semibold text-white mb-1">Set Up Your Profile</h1>
          <p className="text-white/50 text-sm">Tell us about your studies so we can personalize your experience</p>
        </div>

        {/* Progress */}
        <div className="flex items-center gap-2 mb-8">
          {STEPS.map((label, i) => (
            <div key={label} className="flex items-center gap-2 flex-1">
              <div className={`flex items-center justify-center w-7 h-7 rounded-full text-xs font-semibold transition-colors ${
                i < step ? 'bg-emerald-500 text-white' :
                i === step ? 'bg-violet-600 text-white' :
                'bg-white/10 text-white/40'
              }`}>
                {i < step ? <Check size={14} /> : i + 1}
              </div>
              <span className={`text-xs font-medium flex-1 ${
                i <= step ? 'text-white' : 'text-white/30'
              }`}>{label}</span>
              {i < STEPS.length - 1 && (
                <div className={`h-px flex-1 ${
                  i < step ? 'bg-emerald-500/50' : 'bg-white/10'
                }`} />
              )}
            </div>
          ))}
        </div>

        {/* Step content */}
        <div className="glass-card rounded-2xl p-6 border border-white/10 min-h-[300px]">
          <AnimatePresence mode="wait" custom={direction}>
            <motion.div
              key={step}
              custom={direction}
              variants={variants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: 0.22, ease: 'easeInOut' }}
            >
              {/* Step 0: Board */}
              {step === 0 && (
                <div>
                  <h2 className="text-lg font-semibold text-white mb-1">Select your Board</h2>
                  <p className="text-white/50 text-sm mb-6">Which education board are you studying under?</p>
                  <div className="space-y-3">
                    {boards.map((board) => (
                      <button
                        key={board.id}
                        onClick={() => setSelectedBoard(board)}
                        className={`w-full flex items-center gap-4 p-4 rounded-xl border transition-all ${
                          selectedBoard?.id === board.id
                            ? 'border-violet-500 bg-violet-500/15'
                            : 'border-white/10 bg-white/5 hover:border-white/20 hover:bg-white/8'
                        }`}
                        data-testid={`board-option-${board.id}`}
                      >
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-600/30 to-violet-800/30 flex items-center justify-center">
                          <Globe size={20} className="text-violet-400" />
                        </div>
                        <div className="text-left">
                          <p className="text-white font-semibold">{board.name}</p>
                          <p className="text-white/50 text-xs">{board.description}</p>
                        </div>
                        {selectedBoard?.id === board.id && (
                          <div className="ml-auto"><Check size={18} className="text-violet-400" /></div>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Step 1: Class */}
              {step === 1 && (
                <div>
                  <h2 className="text-lg font-semibold text-white mb-1">Select your Class</h2>
                  <p className="text-white/50 text-sm mb-6">Which class are you currently in?</p>
                  {loading ? (
                    <div className="flex justify-center py-8"><Loader2 size={24} className="animate-spin text-violet-400" /></div>
                  ) : (
                    <div className="grid grid-cols-2 gap-3">
                      {classes.map((cls) => (
                        <button
                          key={cls.id}
                          onClick={() => setSelectedClass(cls)}
                          className={`flex flex-col items-center gap-3 p-5 rounded-xl border transition-all ${
                            selectedClass?.id === cls.id
                              ? 'border-violet-500 bg-violet-500/15'
                              : 'border-white/10 bg-white/5 hover:border-white/20'
                          }`}
                          data-testid={`class-option-${cls.id}`}
                        >
                          <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center">
                            {cls.name.includes('11') || cls.name.includes('2nd') ? (
                              <BookOpen size={20} className="text-violet-400" />
                            ) : (
                              <GraduationCap size={20} className="text-violet-400" />
                            )}
                          </div>
                          <div className="text-center">
                            <p className="text-white font-semibold text-sm">{cls.name}</p>
                            <p className="text-white/40 text-xs">{cls.description}</p>
                          </div>
                          {selectedClass?.id === cls.id && <Check size={16} className="text-violet-400" />}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Step 2: Stream */}
              {step === 2 && (
                <div>
                  <h2 className="text-lg font-semibold text-white mb-1">Select your Stream</h2>
                  <p className="text-white/50 text-sm mb-6">What stream are you studying?</p>
                  {loading ? (
                    <div className="flex justify-center py-8"><Loader2 size={24} className="animate-spin text-violet-400" /></div>
                  ) : (
                    <div className="space-y-3">
                      {streams.map((stream) => {
                        const Icon = getStreamIcon(stream.name);
                        const colorClass = getStreamColor(stream.name);
                        return (
                          <button
                            key={stream.id}
                            onClick={() => setSelectedStream(stream)}
                            className={`w-full flex items-center gap-4 p-4 rounded-xl border transition-all ${
                              selectedStream?.id === stream.id
                                ? 'border-violet-500 bg-violet-500/15'
                                : 'border-white/10 bg-white/5 hover:border-white/20'
                            }`}
                            data-testid={`stream-option-${stream.id}`}
                          >
                            <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${colorClass} flex items-center justify-center border`}>
                              <Icon size={18} className="text-white" />
                            </div>
                            <div className="text-left">
                              <p className="text-white font-semibold">{stream.name}</p>
                              <p className="text-white/50 text-xs">{stream.description}</p>
                            </div>
                            {selectedStream?.id === stream.id && <div className="ml-auto"><Check size={18} className="text-violet-400" /></div>}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between mt-6">
          {step > 0 ? (
            <Button
              variant="ghost"
              onClick={goBack}
              className="text-white/70 hover:text-white hover:bg-white/10"
              data-testid="onboarding-back-button"
            >
              <ChevronLeft size={16} className="mr-1" /> Back
            </Button>
          ) : <div />}

          {step < 2 ? (
            <Button
              onClick={goNext}
              disabled={!canGoNext[step]}
              className="bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-40"
              data-testid="onboarding-next-button"
            >
              Next <ChevronRight size={16} className="ml-1" />
            </Button>
          ) : (
            <Button
              onClick={handleFinish}
              disabled={!canGoNext[2] || saving}
              className="bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-40"
              data-testid="onboarding-finish-button"
            >
              {saving ? <Loader2 size={16} className="animate-spin mr-1" /> : <Sparkles size={16} className="mr-1" />}
              {saving ? 'Saving...' : 'Start Studying'}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
