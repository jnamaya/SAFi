/**
 * Generated agent marks — initials on a flat fill, emitted as an inline
 * `data:` SVG.
 *
 * WHY THIS EXISTS. The built-in agents used to ship illustrated cartoon
 * portraits (`fiduciary.svg`, `tutor.svg`, `health_navigator.svg`,
 * `bible_scholar.svg`). Three problems, in the order they matter:
 *
 *   1. A human face is the wrong affordance for a compliance product. A
 *      friendly cartoon person answering a suitability or a symptom question
 *      invites exactly the para-social trust the pipeline exists to constrain,
 *      and it undercuts in pictures the AI disclosure the footer makes in text.
 *   2. They failed the one job an avatar can legitimately do here. SAFi is
 *      multi-agent and each agent carries a different policy, value set and
 *      thresholds, so *which agent answered* is governance-relevant — but all
 *      four portraits shared a face shape and a hoodie silhouette and differed
 *      only in hair colour. At the 20–42px they render at they were
 *      indistinguishable, so they cost gutter space and signalled nothing.
 *   3. All four read as one gender and one age bracket.
 *
 * A monogram fixes all three: it is legible at 20px, carries no anthropomorphic
 * claim, and generates for any agent name — including an org's custom agents,
 * which previously fell back to `safi.svg` and so wore the vendor's logo on the
 * customer's own agent.
 *
 * Returns a URL string, so the `getAvatarForProfile(name) -> url` contract every
 * call site already uses is unchanged. `img-src 'self' data: https:`
 * (`safi_app/__init__.py`) permits the `data:` form.
 */

/**
 * The three fills. DO NOT "brighten" these — they are a computed result, and
 * every number below was measured, not chosen by eye:
 *
 *   fill vs white glyph   >= 4.91:1   (a letterform is read as text, so the
 *                                      3:1 non-text floor is not enough)
 *   fill vs light surface >= 4.91:1   (#ffffff, `.ai-avatar img` background)
 *   fill vs dark surface  >= 3.41:1   (#1a1a1a, `.dark .ai-avatar img`)
 *   worst all-pairs CVD ΔE  9.1       (OKLab x100, min of protan/deutan; >= 8 target)
 *   worst all-pairs normal ΔE 22.5    (unsimulated; >= 15 hard floor)
 *
 * ALL-PAIRS, not adjacent, is the correct pairlist: two agent marks can appear
 * beside any other in the picker, the sidebar or a mixed conversation, so there
 * is no fixed adjacency to exploit.
 *
 * WHY ONLY THREE. Every fill is pinned to a narrow lightness band by the three
 * contrast gates above — dark enough for a white glyph, light enough to lift
 * off a near-black surface. That collapses the usable colour volume to a thin
 * disc in which no four hues sit 15 ΔE apart. A fourth slot was searched for
 * properly and does not exist: the only passing four-hue sets all require a
 * near-gamut-edge magenta (`#e0027e`), which drops the worst pair to 8.0/16.6
 * and looks garish beside a deliberately calm chat surface. A neutral fourth
 * slot fails too, and for a structural reason — with no chroma to separate it
 * from the background it must be lighter, which breaks the white glyph.
 *
 * Three is sufficient because COLOUR IS NOT THE IDENTITY CHANNEL HERE — the
 * initials are, and they are always rendered. Two agents sharing a fill still
 * read as different marks. Collisions are unavoidable at any slot count anyway,
 * since custom agents hash into the same set.
 *
 * (Hues are slots 1–3 of the documented categorical palette — blue, orange,
 * aqua — stepped darker for the white glyph. That trio is also the one the
 * source palette documents as all-pairs-safe in both modes.)
 */
const MARK_FILLS = ['#006eda', '#c64600', '#007e56'];

const GLYPH = '#ffffff';

/** Articles and connectives that carry no identity — "The Fiduciary" -> "F". */
const SKIP_WORDS = new Set([
  'the', 'a', 'an', 'of', 'and', 'for', 'my',
  // Common connectives in the other languages an org is likely to name an agent
  // in — without these, "Ética y Cumplimiento" initials as "EY" not "EC".
  'y', 'e', 'de', 'del', 'la', 'el', 'et', 'du', 'des', 'und', 'der', 'die',
]);

/**
 * Collapse a display name and its sanitized backend key to one form, so
 * "The Health Navigator", "health navigator" and "the_health_navigator" all
 * resolve to the same mark.
 *
 * This replaces ~15 hand-written per-agent name aliases in
 * `getAvatarForProfile`. That aliasing is what let `health_navigator.svg` and
 * `the_health_navigator.svg` drift into byte-identical duplicates.
 */
export function normalizeAgentName(name) {
  return String(name == null ? '' : name)
    .replace(/[_\-]+/g, ' ')
    // Decompose then drop combining marks, so "Ética" yields E rather than
    // losing its first letter to the a-z filter below. An org can name an agent
    // in any language it likes.
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(w => w && !SKIP_WORDS.has(w))
    .join(' ');
}

/**
 * Up to two initials. Only `[A-Z0-9]` survives, which is what makes embedding
 * the result in SVG markup safe by construction rather than by escaping —
 * there is no character left that could close a tag or an attribute.
 */
export function agentInitials(name) {
  const words = normalizeAgentName(name).split(' ').filter(Boolean);
  if (!words.length) return 'A';
  const letters = words.slice(0, 2).map(w => w[0]);
  // A single-word name gives one letter; two words give two. Never three — at
  // 20px a third glyph is a smudge.
  return letters.join('').toUpperCase().slice(0, 2);
}

/** FNV-1a, 32-bit. Stable across reloads, devices and sessions. */
function hash32(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/**
 * Which fill an agent gets. Keyed on the NORMALIZED NAME, deliberately — not on
 * roster position.
 *
 * Consequence to know about: an agent's mark colour will NOT match its line
 * colour in the Audit Hub trend chart, which slots off the org roster
 * (`seriesColor()` in `ui-settings-dashboard.js`). Making them agree was
 * considered and rejected — it would mean threading roster order into a
 * function called from contexts with no roster loaded, and it would change an
 * agent's identity colour whenever somebody adds an agent. Stable-per-entity
 * beats coherent-with-one-chart.
 */
/**
 * The built-in agents get a curated slot rather than a hashed one.
 *
 * Left to the hash they clumped: Fiduciary and Health Navigator both landed on
 * aqua while blue went unused entirely, which is the worst case for the two
 * agents a visitor is most likely to see side by side. With three slots and
 * seven built-ins some sharing is unavoidable, so it is spread deliberately —
 * the pairs that do share a fill are the ones least likely to be confused, and
 * their initials differ anyway.
 *
 * Keys are normalized names. Unlisted agents (every org-authored one) fall
 * through to the hash.
 */
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

/**
 * @param {string} name Agent display name or sanitized backend key.
 * @returns {string} A `data:image/svg+xml` URL suitable for `<img src>`.
 */
export function agentMark(name) {
  const key = normalizeAgentName(name);
  if (_cache.has(key)) return _cache.get(key);

  const initials = agentInitials(name);
  const fill = MARK_FILLS[agentMarkSlot(name)];
  // One glyph gets more room than two. Weight 600 rather than 700: at this size
  // bold letterforms close up their counters and read as a blob.
  const size = initials.length > 1 ? 16 : 19;

  // Full-bleed square, NOT a circle. Every call site applies its own radius
  // (`rounded-md`, `rounded-lg`, `rounded-2xl`, `50%`), so painting a circle
  // here would leave opaque corners showing against the tinted card
  // backgrounds in the agent settings grid. Let CSS do the clipping.
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">` +
    `<rect width="40" height="40" fill="${fill}"/>` +
    `<text x="20" y="20" dy="0.35em" text-anchor="middle" fill="${GLYPH}" ` +
    `font-family="system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif" ` +
    `font-size="${size}" font-weight="600" letter-spacing="0.5">${initials}</text>` +
    `</svg>`;

  // encodeURIComponent, not base64: btoa throws on non-Latin1, and an org can
  // name an agent anything. It also percent-encodes `"` and `#`, which is what
  // keeps the result safe to interpolate into an HTML src attribute.
  const url = `data:image/svg+xml,${encodeURIComponent(svg)}`;
  _cache.set(key, url);
  return url;
}
