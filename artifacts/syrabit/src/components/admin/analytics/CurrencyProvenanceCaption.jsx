const fmtInr = (n) =>
  `₹${Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
const fmtUsd = (n) =>
  `$${Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 2 })}`;

function fmtAsOf(iso) {
  if (!iso) return 'unknown';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'unknown';
    return d.toISOString().slice(0, 10);
  } catch {
    return 'unknown';
  }
}

export function describeBreakdown(breakdown) {
  if (!breakdown) return null;
  const inr = Number(breakdown.inr_native) || 0;
  const usdNative = Number(breakdown.usd_native) || 0;
  const usdAsInr = Number(breakdown.inr_from_usd) || 0;
  if (usdNative <= 0) {
    return `Includes Razorpay only (${fmtInr(inr)}).`;
  }
  const rate = breakdown.fx_rate ? Number(breakdown.fx_rate).toFixed(4) : '—';
  const source = breakdown.fx_source || 'unknown';
  const asOf = fmtAsOf(breakdown.fx_fetched_at);
  return `Includes: Razorpay (${fmtInr(inr)}) + Stripe (${fmtUsd(usdNative)} → ${fmtInr(usdAsInr)} @ rate ${rate}, source: ${source}, as of ${asOf}).`;
}

export function breakdownTooltip(breakdown) {
  if (!breakdown) return '';
  const usdNative = Number(breakdown.usd_native) || 0;
  if (usdNative <= 0) return '';
  const usdAsInr = Number(breakdown.inr_from_usd) || 0;
  const rate = breakdown.fx_rate ? Number(breakdown.fx_rate).toFixed(4) : '—';
  const source = breakdown.fx_source || 'unknown';
  return `USD slice: ${fmtUsd(usdNative)} → ${fmtInr(usdAsInr)} @ ${rate} (${source})`;
}

export default function CurrencyProvenanceCaption({ breakdown, className = '' }) {
  const text = describeBreakdown(breakdown);
  if (!text) return null;
  return (
    <p
      className={`text-[11px] text-gray-500 leading-snug ${className}`}
      title={breakdownTooltip(breakdown)}
    >
      {text}
    </p>
  );
}
