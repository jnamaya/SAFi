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

export function formatTime(date) {
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

export async function responseToJsonSafe(res) {
  try {
    const t = await res.text();
    return t ? JSON.parse(t) : null;
  } catch {
    return null;
  }
}
