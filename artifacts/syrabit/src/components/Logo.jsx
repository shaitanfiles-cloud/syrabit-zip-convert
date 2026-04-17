/**
 * Logo — Syrabit.ai brand logo component.
 * Uses the official Syrabit.ai S-mark image.
 */

// ── Size map ────────────────────────────────────────────────────────────────
const SIZE_MAP = {
  xs:    16,
  sm:    28,
  md:    36,
  lg:    52,
  xl:    72,
  '2xl': 96,
};

/**
 * LogoMark — icon only (the S-mark image).
 */
export const LogoMark = ({ size = 'md', className = '', style = {} }) => {
  const px = SIZE_MAP[size] ?? SIZE_MAP.md;
  // Serve a correctly-sized variant. The 502x486 master is wasteful for the
  // 16-72px slots we render at; ship a 56px variant for ≤sm and a 144px
  // variant (covers up to 72px display @ 2x DPR) for everything larger.
  const src = px <= 28 ? '/logo-56.webp' : '/logo-144.webp';
  return (
    <span className={className} style={{ display: 'inline-flex', flexShrink: 0, ...style }}>
      <img
        src={src}
        alt="Syrabit.ai logo"
        width={px}
        height={px}
        decoding="async"
        style={{ width: px, height: px, borderRadius: px * 0.25, objectFit: 'cover', flexShrink: 0 }}
      />
    </span>
  );
};

/**
 * LogoFull — icon + "Syrabit.ai" wordmark.
 */
export const LogoFull = ({
  size = 'md',
  className = '',
  textClassName = '',
  hideText = false,
  hideIcon = false,
}) => {
  const px = SIZE_MAP[size] ?? SIZE_MAP.md;
  const textSizes = {
    xs:    'text-xs',
    sm:    'text-sm',
    md:    'text-base',
    lg:    'text-xl',
    xl:    'text-2xl',
    '2xl': 'text-3xl',
  };

  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      {!hideIcon && (
        <img
          src={px <= 28 ? '/logo-56.webp' : '/logo-144.webp'}
          alt="Syrabit.ai logo"
          width={px}
          height={px}
          decoding="async"
          style={{ width: px, height: px, borderRadius: px * 0.25, objectFit: 'cover', flexShrink: 0 }}
        />
      )}
      {!hideText && (
        <span
          className={`font-bold tracking-tight ${textSizes[size] ?? textSizes.md} ${textClassName}`}
        >
          Syrabit<span style={{ color: 'hsl(var(--primary))' }}>.ai</span>
        </span>
      )}
    </span>
  );
};

export const LOGO_URL = '/logo.webp';
