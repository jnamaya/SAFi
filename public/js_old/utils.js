const TS_PREFIX = 'safi_msg_ts:';

function hashStr(str) {
  let h = 5381;
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) + h) + str.charCodeAt(i);
    h |= 0;
  }
  return (h >>> 0).toString(36);
}

function tsKey(convoId, index, role, content) {
  return `${TS_PREFIX}${convoId}:${index}:${role}:${hashStr(content || '')}`;
}

export function getOrInitTimestamp(convoId, index, role, content) {
  const key = tsKey(convoId, index, role, content);
  const saved = localStorage.getItem(key);
  if (saved) return new Date(parseInt(saved));
  const now = Date.now();
  localStorage.setItem(key, String(now));
  return new Date(now);
}

export function setTimestamp(convoId, index, role, content, date) {
  const key = tsKey(convoId, index, role, content);
  localStorage.setItem(key, String((date instanceof Date ? date : new Date(date)).getTime()));
}

/**
 * Formats a Date object into a string like "10:30 AM".
 * @param {Date} date The date to format.
 * @returns {string} The formatted time string.
 */
export function formatTime(date) {
  if (!(date instanceof Date)) {
    return '';
  }
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

/**
 * A utility function for escaping HTML to prevent XSS attacks.
 * @param {string} str The string to escape.
 * @returns {string} The escaped string.
 */
export function escapeHtml(str) {
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

export async function responseToJsonSafe(res) {
  try {
    const t = await res.text();
    return t ? JSON.parse(t) : null;
  } catch {
    return null;
  }
}
