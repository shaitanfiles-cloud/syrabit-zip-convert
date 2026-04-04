import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Star, X } from 'lucide-react';
import { API_BASE } from '@/utils/api';

const STORAGE_KEY = 'syrabit_google_review_dismissed';
const POPUP_DELAY_MS = 6000;

function GoogleGLogo({ size = 48 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A10.96 10.96 0 0 0 1 12c0 1.77.42 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05" />
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
    </svg>
  );
}

function MiniReviewCard({ review, index }) {
  const filled = Math.round(review.rating);
  const initials = review.author_name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);

  const gradients = [
    'linear-gradient(135deg,#7c3aed,#8b5cf6)',
    'linear-gradient(135deg,#2563eb,#06b6d4)',
    'linear-gradient(135deg,#059669,#14b8a6)',
    'linear-gradient(135deg,#dc2626,#f97316)',
    'linear-gradient(135deg,#7c3aed,#ec4899)',
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3 + index * 0.1, duration: 0.5 }}
      className="rounded-2xl p-4 flex flex-col gap-2"
      style={{
        background: 'rgba(255,255,255,0.06)',
        border: '1px solid rgba(255,255,255,0.08)',
        minWidth: 220,
        maxWidth: 280,
      }}
    >
      <div className="flex items-center gap-0.5">
        {[...Array(5)].map((_, i) => (
          <Star
            key={i}
            className={`w-3.5 h-3.5 ${i < filled ? 'fill-amber-400 text-amber-400' : 'fill-gray-600 text-gray-600'}`}
          />
        ))}
      </div>
      <p
        className="text-xs leading-relaxed line-clamp-3"
        style={{ color: 'rgba(255,255,255,0.60)' }}
      >
        "{review.text}"
      </p>
      <div className="flex items-center gap-2 pt-1">
        {review.profile_photo_url ? (
          <img
            src={review.profile_photo_url}
            alt=""
            className="w-6 h-6 rounded-full object-cover flex-shrink-0"
            referrerPolicy="no-referrer"
          />
        ) : (
          <div
            className="w-6 h-6 rounded-full flex items-center justify-center text-white flex-shrink-0"
            style={{ background: gradients[index % gradients.length], fontSize: 9, fontWeight: 700 }}
          >
            {initials}
          </div>
        )}
        <span className="text-xs font-medium text-white truncate">{review.author_name}</span>
      </div>
    </motion.div>
  );
}

export default function GoogleReviewPopup() {
  const [visible, setVisible] = useState(false);
  const [reviews, setReviews] = useState([]);
  const [placeId, setPlaceId] = useState('');
  const [overallRating, setOverallRating] = useState(null);
  const [totalRatings, setTotalRatings] = useState(null);

  const dismiss = useCallback(() => {
    setVisible(false);
    try {
      localStorage.setItem(STORAGE_KEY, 'dismissed');
    } catch {}
  }, []);

  const handleReview = useCallback(() => {
    try {
      localStorage.setItem(STORAGE_KEY, 'reviewed');
    } catch {}
    setVisible(false);
  }, []);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) return;
    } catch {}

    let cancelled = false;

    async function loadAndShow() {
      try {
        const res = await fetch(`${API_BASE}/content/google-reviews`);
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        if (!data.configured || !data.place_id) return;

        if (!data.reviews || data.reviews.length === 0) return;

        setPlaceId(data.place_id);
        setReviews(data.reviews.slice(0, 3));
        if (data.overall_rating) setOverallRating(data.overall_rating);
        if (data.total_ratings) setTotalRatings(data.total_ratings);

        setTimeout(() => {
          if (!cancelled) setVisible(true);
        }, POPUP_DELAY_MS);
      } catch {}
    }

    loadAndShow();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (visible) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [visible]);

  const reviewUrl = placeId
    ? `https://search.google.com/local/writereview?placeid=${placeId}`
    : '';

  if (!placeId) return null;

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.35 }}
          className="fixed inset-0 z-[9999] flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(12px)' }}
          onClick={dismiss}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 40 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.92, y: 30 }}
            transition={{ type: 'spring', damping: 28, stiffness: 320 }}
            onClick={(e) => e.stopPropagation()}
            className="relative w-full max-w-lg mx-4 rounded-3xl overflow-hidden"
            style={{
              background: 'linear-gradient(170deg, #0f0f1a 0%, #1a1028 40%, #0d0d18 100%)',
              border: '1px solid rgba(255,255,255,0.10)',
              boxShadow: '0 40px 120px rgba(124,58,237,0.25), 0 0 0 1px rgba(255,255,255,0.05)',
            }}
          >
            <div
              className="absolute top-0 left-0 right-0 h-1"
              style={{ background: 'linear-gradient(90deg, #4285F4, #34A853, #FBBC05, #EA4335)' }}
            />

            <button
              onClick={dismiss}
              className="absolute top-4 right-4 w-9 h-9 rounded-full flex items-center justify-center transition-colors z-10"
              style={{
                background: 'rgba(255,255,255,0.06)',
                color: 'rgba(255,255,255,0.50)',
                border: '1px solid rgba(255,255,255,0.08)',
              }}
              aria-label="Close"
            >
              <X size={18} />
            </button>

            <div className="px-6 pt-10 pb-4 text-center">
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', delay: 0.15, damping: 15 }}
                className="mx-auto w-20 h-20 rounded-2xl flex items-center justify-center mb-6"
                style={{
                  background: 'rgba(255,255,255,0.06)',
                  border: '1px solid rgba(255,255,255,0.10)',
                  boxShadow: '0 8px 32px rgba(66,133,244,0.15)',
                }}
              >
                <GoogleGLogo size={42} />
              </motion.div>

              <h2
                className="text-white mb-2"
                style={{ fontSize: 'clamp(1.3rem, 4vw, 1.75rem)', fontWeight: 800, letterSpacing: '-0.02em' }}
              >
                Love Syrabit.ai?
              </h2>
              <p className="text-sm mb-1" style={{ color: 'rgba(255,255,255,0.55)' }}>
                Your review helps other students discover us
              </p>

              {overallRating && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.25 }}
                  className="flex items-center justify-center gap-2 mt-3"
                >
                  <div className="flex items-center gap-0.5">
                    {[...Array(5)].map((_, i) => (
                      <Star
                        key={i}
                        className={`w-4 h-4 ${i < Math.round(overallRating) ? 'fill-amber-400 text-amber-400' : 'fill-gray-600 text-gray-600'}`}
                      />
                    ))}
                  </div>
                  <span className="text-sm font-bold text-white">{overallRating}</span>
                  {totalRatings && (
                    <span className="text-xs" style={{ color: 'rgba(255,255,255,0.40)' }}>
                      ({totalRatings} reviews)
                    </span>
                  )}
                </motion.div>
              )}
            </div>

            {reviews.length > 0 && (
              <div className="px-6 pb-4">
                <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-hide">
                  {reviews.map((r, i) => (
                    <MiniReviewCard key={`${r.author_name}-${i}`} review={r} index={i} />
                  ))}
                </div>
              </div>
            )}

            <div className="px-6 pb-8 pt-2 flex flex-col gap-3">
              <motion.a
                href={reviewUrl}
                target="_blank"
                rel="noopener noreferrer"
                onClick={handleReview}
                whileHover={{ scale: 1.02, y: -1 }}
                whileTap={{ scale: 0.98 }}
                className="w-full flex items-center justify-center gap-2.5 text-white font-bold rounded-xl"
                style={{
                  height: 52,
                  fontSize: '1rem',
                  background: 'linear-gradient(135deg, #4285F4, #34A853)',
                  boxShadow: '0 8px 32px rgba(66,133,244,0.35)',
                }}
              >
                <GoogleGLogo size={22} />
                Write a Review on Google
              </motion.a>

              <button
                onClick={dismiss}
                className="w-full text-center text-sm font-medium py-2.5 rounded-xl transition-colors"
                style={{ color: 'rgba(255,255,255,0.35)' }}
              >
                Maybe later
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
