import { onCLS, onINP, onLCP, onFCP, onTTFB } from 'web-vitals';

function sendToPostHog(metric) {
  try {
    if (window.posthog && typeof window.posthog.capture === 'function') {
      window.posthog.capture('web_vital', {
        metric_name: metric.name,
        metric_value: metric.value,
        metric_delta: metric.delta,
        metric_id: metric.id,
        metric_rating: metric.rating,
        navigation_type: metric.navigationType,
        page_path: window.location.pathname,
      });
    }
  } catch {}
}

function sendToGA4(metric) {
  try {
    if (typeof window.gtag === 'function') {
      window.gtag('event', metric.name, {
        value: Math.round(metric.name === 'CLS' ? metric.delta * 1000 : metric.delta),
        event_category: 'Web Vitals',
        event_label: metric.id,
        non_interaction: true,
      });
    }
  } catch {}
}

function reportMetric(metric) {
  sendToPostHog(metric);
  sendToGA4(metric);
}

export function initWebVitals() {
  if (import.meta.env.DEV) return;
  onCLS(reportMetric);
  onINP(reportMetric);
  onLCP(reportMetric);
  onFCP(reportMetric);
  onTTFB(reportMetric);
}
