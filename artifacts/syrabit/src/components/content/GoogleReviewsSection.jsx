import { useEffect, useState } from 'react';
import { Star, ExternalLink, MessageSquarePlus } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import { StarRating } from '@/pages/profile/shared';
import { API_BASE } from '@/utils/api';

let _reviewsPromise = null;
let _reviewsCache = null;
export function fetchReviewsOnce() {
  if (_reviewsCache) return Promise.resolve(_reviewsCache);
  if (_reviewsPromise) return _reviewsPromise;
  _reviewsPromise = fetch(`${API_BASE}/reviews/google`, { credentials: 'omit' })
    .then(r => (r.ok ? r.json() : null))
    .then(json => { _reviewsCache = json; return json; })
    .catch(() => null)
    .finally(() => { _reviewsPromise = null; });
  return _reviewsPromise;
}
function useGoogleReviews() {
  const [data, setData] = useState(_reviewsCache);
  const [loading, setLoading] = useState(!_reviewsCache);
  useEffect(() => {
    let cancelled = false;
    fetchReviewsOnce().then(json => {
      if (cancelled) return;
      setData(json || null);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);
  return { data, loading };
}

function formatAvg(value) {
  const num = Number(value || 0);
  if (!num) return '0.0';
  return (Math.round(num * 10) / 10).toFixed(1);
}

function ReviewCard({ review }) {
  const [expanded, setExpanded] = useState(false);
  const text = review.text || '';
  const isLong = text.length > 320;
  const display = expanded || !isLong ? text : text.slice(0, 320).trimEnd() + '…';
  return (
    <div className="rounded-2xl border border-border/40 bg-card/60 p-5 flex flex-col gap-3 h-full">
      <div className="flex items-center gap-3">
        {review.photoUrl ? (
          <img
            src={review.photoUrl}
            alt={review.author}
            loading="lazy"
            referrerPolicy="no-referrer"
            className="w-10 h-10 rounded-full object-cover bg-muted"
          />
        ) : (
          <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center text-sm font-semibold text-muted-foreground">
            {(review.author || '?').slice(0, 1).toUpperCase()}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-foreground truncate">{review.author}</div>
          <div className="flex items-center gap-2 mt-0.5">
            <StarRating value={review.rating} max={5} />
            <span className="text-xs text-muted-foreground">{review.relativeTime}</span>
          </div>
        </div>
      </div>
      <p className="text-sm leading-relaxed text-foreground/90 whitespace-pre-line">{display}</p>
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded(v => !v)}
          className="self-start text-xs font-medium text-violet-600 hover:text-violet-700"
        >
          {expanded ? 'Show less' : 'Read more'}
        </button>
      )}
    </div>
  );
}

function filterReviewsByKeywords(reviews, keywords) {
  if (!Array.isArray(reviews) || reviews.length === 0) return reviews || [];
  const kws = (Array.isArray(keywords) ? keywords : [keywords])
    .filter(k => typeof k === 'string' && k.trim().length >= 3)
    .map(k => k.toLowerCase().trim());
  if (kws.length === 0) return reviews;
  const matches = reviews.filter(r => {
    const text = (r && r.text ? String(r.text) : '').toLowerCase();
    if (!text) return false;
    return kws.some(k => text.includes(k));
  });
  return matches.length > 0 ? matches : reviews;
}

export default function GoogleReviewsSection({
  heading = 'What students say',
  subheading = '',
  keywords = null,
}) {
  const { data, loading } = useGoogleReviews();

  if (loading) {
    return (
      <section className="mt-12 max-w-5xl mx-auto px-4">
        <Skeleton className="h-6 w-64 mb-4" />
        <Skeleton className="h-4 w-96 mb-6" />
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-2xl" />
          ))}
        </div>
      </section>
    );
  }

  if (!data || !Array.isArray(data.reviews) || data.reviews.length === 0) {
    return null;
  }

  const filteredReviews = filterReviewsByKeywords(data.reviews, keywords);
  const avg = formatAvg(data.averageRating);
  const total = Number(data.totalCount || 0);
  const writeReviewUrl = data.writeReviewUrl || data.googleUrl || '';

  return (
    <section className="mt-12 max-w-5xl mx-auto px-4" aria-label="Google reviews">
      <div className="rounded-3xl border border-border/40 bg-gradient-to-br from-amber-50/40 via-background to-violet-50/30 p-6 sm:p-8">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div>
            <h2 className="text-xl sm:text-2xl font-bold text-foreground">{heading}</h2>
            {subheading && (
              <p className="text-sm text-muted-foreground mt-1">{subheading}</p>
            )}
            <div className="flex items-center gap-2 mt-3">
              <span className="text-3xl font-bold text-amber-600 leading-none">{avg}</span>
              <div className="flex flex-col">
                <StarRating value={Math.round(Number(data.averageRating) || 0)} max={5} />
                <span className="text-xs text-muted-foreground mt-0.5">
                  {total > 0
                    ? `${total.toLocaleString()} Google review${total === 1 ? '' : 's'}`
                    : 'Google reviews'}
                </span>
              </div>
            </div>
          </div>
          {writeReviewUrl && (
            <a
              href={writeReviewUrl}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold transition-colors shadow-sm self-start"
            >
              <MessageSquarePlus size={16} />
              Write a review on Google
            </a>
          )}
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredReviews.slice(0, 6).map((r, i) => (
            <ReviewCard key={i} review={r} />
          ))}
        </div>

        {data.googleUrl && (
          <div className="mt-5 text-right">
            <a
              href={data.googleUrl}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-violet-600 hover:text-violet-700"
            >
              Read more on Google <ExternalLink size={14} />
            </a>
          </div>
        )}
      </div>
    </section>
  );
}

export function ReviewsAggregateRatingJsonLd({ id, name, url }) {
  const { data } = useGoogleReviews();
  const agg = data && Number(data.totalCount) > 0 && Number(data.averageRating) > 0
    ? {
        ratingValue: Math.round(Number(data.averageRating) * 10) / 10,
        ratingCount: Number(data.totalCount),
      }
    : null;
  useEffect(() => {
    if (!agg || typeof document === 'undefined') return;
    const elId = id || 'google-reviews-aggregaterating-jsonld';
    document.getElementById(elId)?.remove();
    const node = {
      '@context': 'https://schema.org',
      '@type': 'LocalBusiness',
      name: name || 'Syrabit.ai',
      url: url || (typeof window !== 'undefined' ? window.location.href : 'https://syrabit.ai'),
      aggregateRating: {
        '@type': 'AggregateRating',
        ratingValue: agg.ratingValue,
        reviewCount: agg.ratingCount,
        bestRating: 5,
        worstRating: 1,
      },
    };
    const s = document.createElement('script');
    s.type = 'application/ld+json';
    s.id = elId;
    s.text = JSON.stringify(node);
    document.head.appendChild(s);
    return () => { document.getElementById(elId)?.remove(); };
  }, [agg, id, name, url]);
  return null;
}
