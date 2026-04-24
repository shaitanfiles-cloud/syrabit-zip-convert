// Task #842 — shared caption helpers for AdminHealth cron pills.
//
// The cf-waf-drift and Trustpilot refresh-cron wrappers both build
// their `renderSubText` output the same way: a primary line that
// reports a heartbeat age (with a fallback when no heartbeat is
// known), optionally joined to extra context with " · ". Tasks #836
// and #838 left two copies of the prose ("Last heartbeat … ago" /
// "No heartbeat recorded yet" and "Last successful heartbeat … ago"
// / "No successful heartbeat recorded") and the join character
// inline in each wrapper. Hoisting them here means a third or
// fourth cron pill can compose its caption from the same primitives
// without copy-pasting the join logic or the empty-state fallbacks.

// Render one heartbeat-age line. When `ageLabel` is a non-empty
// string (e.g. "1h", "5m", "2d"), returns "<prefix> <ageLabel> ago";
// otherwise returns the `fallback` string verbatim. The wrappers'
// previous inline ternaries used the exact same shape — keeping it
// identical here so visual output is unchanged.
export function captionLine(prefix, ageLabel, fallback) {
  return ageLabel ? `${prefix} ${ageLabel} ago` : fallback;
}

// Join caption parts with " · ", dropping any empty / nullish parts
// so an absent suffix never renders as an orphan separator (the
// trustpilot test explicitly guards against `recorded · ` slipping
// through). Empty input yields an empty string, matching the
// previous behaviour where a missing suffix collapsed to "".
export function joinCaptionParts(parts) {
  return (parts || []).filter(Boolean).join(' · ');
}
