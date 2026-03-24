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
  return (
    <span className={className} style={{ display: 'inline-flex', flexShrink: 0, ...style }}>
      <img
        src="/logo.png"
        alt="Syrabit.ai logo"
        width={px}
        height={px}
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
          src="/logo.png"
          alt="Syrabit.ai logo"
          width={px}
          height={px}
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

export const LOGO_URL = '/logo.png';
