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
  if (!(date instanceof Date)) {
    return '';
  }
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

export function formatRelativeTime(timestamp) {
    if (!timestamp) return '';

    const date = (timestamp instanceof Date) ? timestamp : new Date(timestamp);
    if (isNaN(date.getTime())) {
        return '';
    }

    const now = new Date();
    const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

    if (seconds > 60 * 60 * 24 * 7) {
        return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }
    
    const days = Math.floor(seconds / 86400);
    if (days > 1) {
        return `${days} days ago`;
    }

    const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
    const isYesterday = date.getFullYear() === yesterday.getFullYear() &&
                        date.getMonth() === yesterday.getMonth() &&
                        date.getDate() === yesterday.getDate();
    if (isYesterday) {
        return 'Yesterday';
    }

    const hours = Math.floor(seconds / 3600);
    if (hours >= 1) {
        return `${hours}h ago`;
    }

    const minutes = Math.floor(seconds / 60);
    if (minutes >= 1) {
        return `${minutes}m ago`;
    }

    return 'Just now';
}


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
