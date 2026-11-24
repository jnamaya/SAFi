const MARK_FILLS = ['#006eda', '#c64600', '#007e56'];

const GLYPH = '#ffffff';

const SKIP_WORDS = new Set([
  'the', 'a', 'an', 'of', 'and', 'for', 'my',
  'y', 'e', 'de', 'del', 'la', 'el', 'et', 'du', 'des', 'und', 'der', 'die',
]);

export function normalizeAgentName(name) {
  return String(name == null ? '' : name)
    .replace(/[_\-]+/g, ' ')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(w => w && !SKIP_WORDS.has(w))
    .join(' ');
}

export function agentInitials(name) {
  const words = normalizeAgentName(name).split(' ').filter(Boolean);
  if (!words.length) return 'A';
  const letters = words.slice(0, 2).map(w => w[0]);
  return letters.join('').toUpperCase().slice(0, 2);
}

function hash32(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

const BUILTIN_SLOTS = {
  'fiduciary': 0,
  'health navigator': 1,
  'socratic tutor': 2,
  'bible scholar': 0,
  'negotiator': 1,
  'philosopher': 2,
  'vault': 0,
};

export function agentMarkSlot(name) {
  const key = normalizeAgentName(name);
  if (!key) return 0;
  if (key in BUILTIN_SLOTS) return BUILTIN_SLOTS[key];
  return hash32(key) % MARK_FILLS.length;
}

const _cache = new Map();

export function agentMark(name) {
  const key = normalizeAgentName(name);
  if (_cache.has(key)) return _cache.get(key);

  const initials = agentInitials(name);
  const fill = MARK_FILLS[agentMarkSlot(name)];
  const size = initials.length > 1 ? 16 : 19;

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">` +
    `<rect width="40" height="40" fill="${fill}"/>` +
    `<text x="20" y="20" dy="0.35em" text-anchor="middle" fill="${GLYPH}" ` +
    `font-family="system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif" ` +
    `font-size="${size}" font-weight="600" letter-spacing="0.5">${initials}</text>` +
    `</svg>`;

  const url = `data:image/svg+xml,${encodeURIComponent(svg)}`;
  _cache.set(key, url);
  return url;
}
