/** Pure tool ordering. The host retains authorization and argument validation. */
export function nextPublicRead(allowed, attempted, browserEnabled) {
  return ['web_read', 'visual_browser', 'web_search'].find(tool =>
    allowed.includes(tool) && !attempted.includes(tool) &&
    (tool !== 'visual_browser' || browserEnabled)) || null;
}
