import { formatTime } from './utils.js';

// ADDED: Enhanced marked.js configuration
marked.setOptions({
  breaks: true, // Render <br> on a single line break
  gfm: true,    // Use GitHub Flavored Markdown for tables, etc.
  mangle: false,
  headerIds: false,
  highlight: function(code, lang) {
    // Use highlight.js for syntax highlighting
    const language = hljs.getLanguage(lang) ? lang : 'plaintext';
    return hljs.highlight(code, { language }).value;
  }
});


export const elements = {
  loginView: document.getElementById('login-view'),
  chatView: document.getElementById('chat-view'),
  loginButton: document.getElementById('login-button'),
  sidebarContainer: document.getElementById('sidebar-container'),
  chatWindow: document.getElementById('chat-window'),
  messageInput: document.getElementById('message-input'),
  sendButton: document.getElementById('send-button'),
  chatTitle: document.getElementById('chat-title'),
  toastContainer: document.getElementById('toast-container'),
  modalBackdrop: document.getElementById('modal-backdrop'),
  conscienceModal: document.getElementById('conscience-modal'),
  deleteAccountModal: document.getElementById('delete-account-modal'),
  composerFooter: document.getElementById('composer-footer'),
  conscienceDetails: document.getElementById('conscience-details'),
  closeConscienceModalBtn: document.getElementById('close-conscience-modal'),
};

let activeToast = null;
let lastRenderedDay = '';

export function openSidebar() {
  document.getElementById('sidebar')?.classList.remove('-translate-x-full');
  document.getElementById('sidebar-overlay')?.classList.remove('hidden');
}

export function closeSidebar() {
  document.getElementById('sidebar')?.classList.add('-translate-x-full');
  document.getElementById('sidebar-overlay')?.classList.add('hidden');
}

export function updateUIForAuthState(user, logoutHandler, profileChangeHandler) {
  if (user) {
    elements.loginView.classList.add('hidden');
    elements.chatView.classList.remove('hidden');
    
    elements.sidebarContainer.innerHTML = `
        <div id="sidebar-overlay" class="fixed inset-0 bg-black/50 z-30 hidden md:hidden"></div>
        <aside id="sidebar" class="fixed inset-y-0 left-0 w-80 bg-white dark:bg-black text-neutral-900 dark:text-white flex flex-col z-40 transform -translate-x-full transition-transform duration-300 ease-in-out md:translate-x-0 h-full border-r border-gray-200 dark:border-gray-800">
          <div class="p-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between shrink-0">
            <div class="flex items-center gap-3">
              <div class="app-logo h-10 w-10">
                <img src="assets/logo.png" alt="SAFi Logo" class="rounded-lg w-full h-full" onerror="this.onerror=null; this.src='https://placehold.co/40x40/22c55e/FFFFFF?text=S'">
              </div>
              <div>
                <h1 class="text-lg font-bold">SAFi</h1>
                <p class="text-xs text-gray-500 dark:text-gray-400">The Ethical Reasoning Engine</p>
              </div>
            </div>
            <button id="close-sidebar-button" type="button" aria-label="Close sidebar" class="p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 md:hidden">
              <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>
          <div class="p-4 shrink-0">
            <button id="new-chat-button" type="button" class="w-full bg-green-600 text-white font-semibold px-4 py-2.5 rounded-lg hover:bg-green-700 transition-colors flex items-center justify-center gap-2 shadow-sm hover:shadow-md">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
              New Chat
            </button>
          </div>
          <nav id="convo-list" aria-label="Conversation history" class="flex-1 overflow-y-auto p-2 space-y-1 custom-scrollbar min-h-0">
            <h3 class="px-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">History</h3>
          </nav>
          <div id="user-profile-container" class="p-4 border-t border-gray-200 dark:border-gray-800 shrink-0">
          </div>
        </aside>
    `;

    const pic = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;
    const name = user.name || user.email || 'User';
    
    document.getElementById('user-profile-container').innerHTML = `
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3 min-w-0">
          <img src="${pic}" alt="User Avatar" class="w-10 h-10 rounded-full">
          <div class="flex-1 min-w-0">
            <p class="text-sm font-semibold truncate">${name}</p>
            <p class="text-xs text-neutral-500 dark:text-neutral-400 truncate">${user.email}</p>
          </div>
        </div>
        <div class="relative" id="settings-menu">
          <button id="settings-button" class="p-2 rounded-full hover:bg-neutral-100 dark:hover:bg-neutral-700">
            <svg class="w-5 h-5 text-neutral-500 dark:text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0 3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
          </button>
          <div id="settings-dropdown" class="absolute bottom-full right-0 mb-2 w-48 bg-white dark:bg-neutral-800 rounded-lg shadow-xl border border-neutral-200 dark:border-neutral-700 hidden z-10">
            <div class="p-2">
              <label for="profile-selector" class="block text-xs font-medium text-neutral-500 dark:text-neutral-400 px-2 mb-1">Active Persona</label>
              <select id="profile-selector" class="w-full text-sm bg-neutral-50 dark:bg-neutral-700 border border-neutral-300 dark:border-neutral-600 rounded-md py-1.5 px-2 focus:ring-green-500 focus:border-green-500"></select>
            </div>
            <div class="border-t border-neutral-200 dark:border-neutral-700 my-1"></div>
            <button id="theme-toggle" class="flex items-center gap-2 w-full text-left px-4 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700">
                <svg id="theme-icon-dark" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path></svg>
                <svg id="theme-icon-light" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>
                <span>Toggle Theme</span>
            </button>
            <div class="border-t border-neutral-200 dark:border-neutral-700 my-1"></div>
            <button id="logout-button" class="block w-full text-left px-4 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700">Sign Out</button>
            <button id="delete-account-btn" class="block w-full text-left px-4 py-2 text-sm text-red-600 dark:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30">Delete Account</button>
          </div>
        </div>
      </div>
      `;
      
    document.getElementById('logout-button').addEventListener('click', logoutHandler);
    document.getElementById('delete-account-btn').addEventListener('click', () => showModal('delete'));
    document.getElementById('profile-selector').addEventListener('change', profileChangeHandler);
    
    const themeToggle = document.getElementById('theme-toggle');
    const updateThemeUI = () => {
        const isDark = document.documentElement.classList.contains('dark');
        const lightIcon = document.getElementById('theme-icon-light');
        const darkIcon = document.getElementById('theme-icon-dark');
        if(lightIcon && darkIcon) {
            lightIcon.style.display = isDark ? 'block' : 'none';
            darkIcon.style.display = isDark ? 'none' : 'block';
        }
    };

    themeToggle.addEventListener('click', () => {
        document.documentElement.classList.toggle('dark');
        localStorage.theme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
        updateThemeUI();
    });
    updateThemeUI();

  } else {
    elements.sidebarContainer.innerHTML = '';
    elements.loginView.classList.remove('hidden');
    elements.chatView.classList.add('hidden');
  }
}

export function populateProfileSelector(profiles, selectedProfileKey) {
    const selector = document.getElementById('profile-selector');
    if (!selector) return;
    selector.innerHTML = '';
    profiles.forEach(profile => {
        const option = document.createElement('option');
        option.value = profile.key;
        option.textContent = profile.name;
        option.selected = profile.key === selectedProfileKey;
        selector.appendChild(option);
    });
}

export function renderConversationLink(convo, handlers) {
  const { switchHandler, renameHandler, deleteHandler } = handlers;
  const link = document.createElement('a');
  link.href = '#';
  link.dataset.id = convo.id;
  link.className = 'group flex items-center justify-between px-3 py-2 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg';
  link.innerHTML = `<span class="truncate">${convo.title || 'Untitled'}</span>
    <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <button data-action="rename" class="p-1 hover:bg-neutral-200 dark:hover:bg-neutral-600 rounded-md" aria-label="Rename"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.5L15.232 5.232z"></path></svg></button>
      <button data-action="delete" class="p-1 hover:bg-neutral-200 dark:hover:bg-neutral-600 rounded-md" aria-label="Delete"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-4v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg></button>
    </div>`;
  link.addEventListener('click', (e) => {
    e.preventDefault();
    const action = e.target.closest('button')?.dataset.action;
    if (action === 'rename') renameHandler(convo.id, convo.title || 'Untitled');
    else if (action === 'delete') deleteHandler(convo.id);
    else switchHandler(convo.id);
  });
  return link;
}

// --- START: NEW FUNCTION ---
// This function creates the simple, large-text greeting.
export function displaySimpleGreeting(firstName) {
  // Ensure no other greeting exists to avoid duplicates
  const existingGreeting = elements.chatWindow.querySelector('.simple-greeting');
  if (existingGreeting) existingGreeting.remove();

  const greetingDiv = document.createElement('div');
  // Added a class for targeting and styling with Tailwind CSS
  greetingDiv.className = 'simple-greeting text-4xl font-bold text-center py-8 text-neutral-800 dark:text-neutral-200';
  greetingDiv.textContent = `Hi ${firstName}`;
  elements.chatWindow.appendChild(greetingDiv);
}
// --- END: NEW FUNCTION ---

export function displayMessage(sender, text, date = new Date(), messageId = null, payload = null, whyHandler = null, options = {}) {
  // When a real message is displayed, remove both the empty state and the simple greeting
  const emptyState = elements.chatWindow.querySelector('.empty-state-container');
  if (emptyState) emptyState.remove();
  const simpleGreeting = elements.chatWindow.querySelector('.simple-greeting');
  if (simpleGreeting) simpleGreeting.remove();

  maybeInsertDayDivider(date);

  const messageContainer = document.createElement('div');
  messageContainer.className = 'message-container';
  if (messageId) {
    messageContainer.dataset.messageId = messageId;
  }

  const messageDiv = document.createElement('div');
  messageDiv.className = `message ${sender}`;

  if (sender === 'ai') {
    messageDiv.innerHTML = `
      <div class="ai-avatar">
        <img src="assets/logo.png" alt="SAFi Avatar" class="w-full h-full rounded-full app-logo">
      </div>
      <div class="ai-content-wrapper">
        <p class="ai-name">SAFi</p>
        <div class="chat-bubble"></div>
        <div class="meta"></div>
      </div>
    `;
    const bubble = messageDiv.querySelector('.chat-bubble');
    bubble.innerHTML = DOMPurify.sanitize(marked.parse(text ?? ''));
  } else {
    const bubbleHtml = DOMPurify.sanitize(marked.parse(text ?? ''));
    const avatarUrl = options.avatarUrl || `https://placehold.co/40x40/7e22ce/FFFFFF?text=U`;
    messageDiv.innerHTML = `
        <div class="user-content-wrapper">
           <div class="chat-bubble">${bubbleHtml}</div>
           <div class="meta"></div>
        </div>
        <div class="user-avatar">
            <img src="${avatarUrl}" alt="User Avatar" class="w-full h-full rounded-full">
        </div>
    `;
  }
  
  const metaDiv = messageDiv.querySelector('.meta');
  const leftMeta = document.createElement('div');
  const rightMeta = document.createElement('div');
  rightMeta.className = 'flex items-baseline gap-3 ml-auto';

  const hasLedger = payload && Array.isArray(payload.ledger) && payload.ledger.length > 0;
  if (hasLedger && whyHandler) {
      const whyButton = document.createElement('button');
      whyButton.className = 'why-btn';
      whyButton.textContent = 'View Ethical Reasoning';
      whyButton.addEventListener('click', () => whyHandler(payload));
      leftMeta.appendChild(whyButton);
  }
  
  metaDiv.appendChild(leftMeta);

  if (sender === 'ai') {
      rightMeta.appendChild(makeCopyButton(text));
  }

  const stampDiv = document.createElement('div');
  stampDiv.className = 'stamp';
  stampDiv.textContent = formatTime(date);
  
  rightMeta.appendChild(stampDiv);
  metaDiv.appendChild(rightMeta);
  
  messageContainer.appendChild(messageDiv);

  elements.chatWindow.appendChild(messageContainer);
  scrollToBottom();
  return messageContainer;
}

export function updateMessageWithAudit(messageId, payload, whyHandler) {
    const messageContainer = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageContainer) return;

    const hasLedger = payload && Array.isArray(payload.ledger) && payload.ledger.length > 0;
    if (!hasLedger) return;

    const metaDiv = messageContainer.querySelector('.meta');
    if (metaDiv && !metaDiv.querySelector('.why-btn')) {
        const whyButton = document.createElement('button');
        whyButton.className = 'why-btn';
        whyButton.textContent = 'View Ethical Reasoning';
        whyButton.addEventListener('click', () => whyHandler(payload));
        
        const leftMeta = metaDiv.querySelector('div:first-child');
        if (leftMeta) {
            leftMeta.appendChild(whyButton);
        } else {
            const newLeftMeta = document.createElement('div');
            newLeftMeta.appendChild(whyButton);
            metaDiv.insertBefore(newLeftMeta, metaDiv.firstChild);
        }
    }
}

export function showLoadingIndicator() {
  const emptyState = elements.chatWindow.querySelector('.empty-state-container');
  if (emptyState) emptyState.remove();
  const simpleGreeting = elements.chatWindow.querySelector('.simple-greeting');
  if (simpleGreeting) simpleGreeting.remove();
  
  maybeInsertDayDivider(new Date());
  const loadingContainer = document.createElement('div');
  loadingContainer.className = 'message-container';
  loadingContainer.innerHTML = `
    <div class="message ai">
        <div class="ai-avatar">
            <img src="assets/logo.png" alt="SAFi Avatar" class="w-full h-full rounded-full app-logo">
        </div>
        <div class="ai-content-wrapper">
             <p class="ai-name">SAFi</p>
            <div class="flex items-center gap-3">
              <div class="thinking-spinner"></div>
              <span id="thinking-status" class="text-gray-500 dark:text-gray-400 italic">Thinking...</span>
            </div>
        </div>
    </div>`;
  elements.chatWindow.appendChild(loadingContainer);
  scrollToBottom();
  return loadingContainer;
}

export function showToast(message, type = 'info', duration = 3000) {
  if (activeToast) activeToast.remove();
  const toast = document.createElement('div');
  const colors = { info: 'bg-blue-500', success: 'bg-green-600', error: 'bg-red-600' };
  toast.className = `toast text-white px-4 py-2 rounded-lg shadow-lg ${colors[type]}`;
  toast.textContent = message;
  elements.toastContainer.appendChild(toast);
  activeToast = toast;
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => {
    toast.classList.remove('show');
    toast.addEventListener('transitionend', () => toast.remove());
    if (activeToast === toast) activeToast = null;
  }, duration);
}

function setupModal(payload) {
    const container = elements.conscienceDetails;
    if (!container) return;
    container.innerHTML = ''; 

    container.insertAdjacentHTML('beforeend', renderIntro(payload));
    container.insertAdjacentHTML('beforeend', renderScoreAndTrend(payload));
    container.insertAdjacentHTML('beforeend', renderLedger(payload.ledger));
    
    container.querySelectorAll('.expand-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const reason = btn.parentElement.querySelector('.reason-text');
            const isTruncated = reason.classList.contains('truncated');
            reason.classList.toggle('truncated');
            btn.textContent = isTruncated ? 'Show Less' : 'Show More';
        });
    });

    const copyBtn = document.getElementById('copy-audit-btn');
    if (copyBtn) {
        const newCopyBtn = copyBtn.cloneNode(true);
        copyBtn.parentNode.replaceChild(newCopyBtn, copyBtn);
        newCopyBtn.addEventListener('click', () => copyAuditToClipboard(payload));
    }
}

export function showModal(kind, data) {
  if (kind === 'conscience') {
    const payload = data || { ledger: [], profile: null, values: [], spirit_score: null, spirit_scores_history: [] };
    setupModal(payload);
    elements.conscienceModal.classList.remove('hidden');
    elements.modalBackdrop.classList.remove('hidden');
  } else if (kind === 'delete') {
    document.getElementById('delete-account-modal').classList.remove('hidden');
    elements.modalBackdrop.classList.remove('hidden');
  }
}

export function closeModal() {
  elements.modalBackdrop.classList.add('hidden');
  elements.conscienceModal.classList.add('hidden');
  document.getElementById('delete-account-modal').classList.add('hidden');
}

function renderIntro(payload) {
    const profileName = payload.profile ? `the <strong>${payload.profile}</strong>` : 'the current';
    return `<p class="text-base text-neutral-600 dark:text-neutral-300 mb-6">This response was shaped by ${profileName} persona. Here’s a breakdown of the reasoning:</p>`;
}

function renderScoreAndTrend(payload) {
    if (payload.spirit_score === null || payload.spirit_score === undefined) return '';

    const score = Math.max(0, Math.min(10, payload.spirit_score));
    const circumference = 50 * 2 * Math.PI;
    const offset = circumference - (score / 10) * circumference;

    const getScoreColor = (s) => {
        if (s >= 8) return 'text-green-500';
        if (s >= 5) return 'text-yellow-500';
        return 'text-red-500';
    };
    
    const colorClass = getScoreColor(score);

    const radialGauge = `
        <div class="relative flex flex-col items-center justify-center">
            <svg class="w-32 h-32 transform -rotate-90">
                <circle class="text-neutral-200 dark:text-neutral-700" stroke-width="8" stroke="currentColor" fill="transparent" r="50" cx="64" cy="64" />
                <circle class="${colorClass.replace('text-', 'stroke-')}" stroke-width="8" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" stroke-linecap="round" stroke="currentColor" fill="transparent" r="50" cx="64" cy="64" />
            </svg>
            <div class="absolute flex flex-col items-center">
                 <span class="text-3xl font-bold ${colorClass}">${score.toFixed(1)}</span>
                 <span class="text-xs text-neutral-500 dark:text-neutral-400">/ 10</span>
            </div>
        </div>
        <h4 class="font-semibold mt-2 text-center">Alignment Score</h4>
        <p class="text-xs text-neutral-500 dark:text-neutral-400 mt-1 text-center max-w-[180px]">Reflects alignment with the active value set.</p>
    `;

    const scores = (payload.spirit_scores_history || []).filter(s => s !== null && s !== undefined).slice(-10);
    let sparkline = '<div class="flex-1 flex items-center justify-center text-sm text-neutral-400">Not enough data for trend.</div>';

    if (scores.length > 1) {
        const width = 200, height = 60, padding = 5;
        const maxScore = 10, minScore = 0;
        const range = maxScore - minScore;
        const points = scores.map((s, i) => {
            const x = (i / (scores.length - 1)) * (width - 2 * padding) + padding;
            const y = height - padding - ((s - minScore) / range) * (height - 2 * padding);
            return `${x},${y}`;
        }).join(' ');

        const lastPoint = points.split(' ').pop().split(',');
        sparkline = `
            <div class="flex-1 pl-4">
                <h4 class="font-semibold mb-2 text-center">Alignment Trend</h4>
                <svg viewBox="0 0 ${width} ${height}" class="w-full h-auto">
                    <polyline fill="none" class="stroke-green-500" stroke-width="2" points="${points}" />
                    <circle fill="${getScoreColor(scores[scores.length-1]).replace('text-','fill-')}" class="stroke-white dark:stroke-neutral-800" r="3" cx="${lastPoint[0]}" cy="${lastPoint[1]}"></circle>
                </svg>
                <p class="text-xs text-neutral-500 dark:text-neutral-400 mt-1 text-center">Recent score history</p>
            </div>
        `;
    }

    return `<div class="grid grid-cols-1 sm:grid-cols-2 gap-6 items-center bg-neutral-50 dark:bg-neutral-800/50 rounded-lg p-4 mb-6">${radialGauge}${sparkline}</div>`;
}

function renderLedger(ledger) {
    if (!ledger || ledger.length === 0) {
        return '<div class="text-sm text-center text-neutral-500 py-4">No specific values were engaged for this response.</div>';
    }

    const groups = {
        upholds: ledger.filter(r => r.score > 0),
        conflicts: ledger.filter(r => r.score < 0),
        neutral: ledger.filter(r => r.score === 0),
    };

    for (const key in groups) {
        groups[key].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    }

    const groupConfig = {
        upholds: { title: 'Upholds', icon: 'M5 13l4 4L19 7', color: 'green' },
        conflicts: { title: 'Conflicts', icon: 'M6 18L18 6M6 6l12 12', color: 'red' },
        neutral: { title: 'Neutral', icon: 'M18 12H6', color: 'neutral' },
    };

    let html = '';
    for (const key of ['upholds', 'conflicts', 'neutral']) {
        if (groups[key].length > 0) {
            const config = groupConfig[key];
            html += `
                <div class="flex items-center gap-3 my-4">
                    <span class="p-1.5 bg-${config.color}-100 dark:bg-${config.color}-900/40 rounded-full">
                        <svg class="w-5 h-5 text-${config.color}-600 dark:text-${config.color}-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${config.icon}"></path></svg>
                    </span>
                    <h4 class="text-base font-semibold text-neutral-800 dark:text-neutral-200">${config.title} (${groups[key].length})</h4>
                    <div class="flex-1 h-px bg-neutral-200 dark:bg-neutral-700"></div>
                </div>
                <div class="space-y-3">
                    ${groups[key].map(renderLedgerItem).join('')}
                </div>
            `;
        }
    }
    return html;
}

function renderLedgerItem(item) {
    const reasonHtml = DOMPurify.sanitize(String(item.reason || ''));
    const maxLength = 120;
    const isLong = reasonHtml.length > maxLength;
    
    const confidenceHtml = item.confidence ? `<div class="text-xs font-medium text-blue-600 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/50 px-2 py-0.5 rounded-full">CONFIDENCE: ${Math.round(item.confidence * 100)}%</div>` : '';

    return `
        <div class="bg-white dark:bg-neutral-800/60 p-4 rounded-lg border border-neutral-200 dark:border-neutral-700/80">
            <div class="flex items-center justify-between gap-4 mb-2">
                <div class="font-semibold text-neutral-800 dark:text-neutral-200">${item.value}</div>
                ${confidenceHtml}
            </div>
            <div class="prose prose-sm dark:prose-invert max-w-none text-neutral-600 dark:text-neutral-400">
                <div class="reason-text ${isLong ? 'truncated' : ''}">${reasonHtml}</div>
                ${isLong ? '<button class="expand-btn">Show More</button>' : ''}
            </div>
        </div>
    `;
}

function copyAuditToClipboard(payload) {
    let text = `SAFi Ethical Reasoning Audit\n`;
    text += `Profile: ${payload.profile || 'N/A'}\n`;
    text += `Alignment Score: ${payload.spirit_score !== null ? payload.spirit_score.toFixed(1) + '/10' : 'N/A'}\n`;
    text += `------------------------------------\n\n`;
    
    if (payload.ledger && payload.ledger.length > 0) {
        const upholds = payload.ledger.filter(r => r.score > 0);
        const conflicts = payload.ledger.filter(r => r.score < 0);
        const neutral = payload.ledger.filter(r => r.score === 0);

        if (upholds.length > 0) {
            text += 'UPHOLDS:\n';
            upholds.forEach(item => {
                text += `- ${item.value} (Confidence: ${Math.round((item.confidence || 0) * 100)}%): ${item.reason}\n`;
            });
            text += '\n';
        }
        if (conflicts.length > 0) {
            text += 'CONFLICTS:\n';
            conflicts.forEach(item => {
                text += `- ${item.value} (Confidence: ${Math.round((item.confidence || 0) * 100)}%): ${item.reason}\n`;
            });
            text += '\n';
        }
        if (neutral.length > 0) {
            text += 'NEUTRAL:\n';
            neutral.forEach(item => {
                text += `- ${item.value} (Confidence: ${Math.round((item.confidence || 0) * 100)}%): ${item.reason}\n`;
            });
        }
    } else {
        text += 'No specific values were engaged for this response.';
    }

    navigator.clipboard.writeText(text).then(() => {
        showToast('Audit copied to clipboard', 'success');
    }, () => {
        showToast('Failed to copy audit', 'error');
    });
}

export function scrollToBottom() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
}

function maybeInsertDayDivider(date) {
  const key = date.toLocaleDateString();
  if (key !== lastRenderedDay) {
    lastRenderedDay = key;
    const div = document.createElement('div');
    div.className = 'flex items-center justify-center my-2';
    div.innerHTML = `<div class="text-xs text-neutral-500 dark:text-neutral-400 px-3 py-1 rounded-full bg-neutral-100 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700">${date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}</div>`;
    elements.chatWindow.appendChild(div);
  }
}

function makeCopyButton(text) {
  const btn = document.createElement('button');
  btn.className = 'meta-btn';
  btn.title = 'Copy Text';
  
  const icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>`;
  btn.innerHTML = icon;

  btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(text);
      showToast('Copied to clipboard', 'success');
    } catch (err) {
      showToast('Failed to copy', 'error');
    }
  });
  return btn;
}

export function displayEmptyState(activeProfile, promptClickHandler) {
  const existingEmptyState = document.querySelector('.empty-state-container');
  if (existingEmptyState) {
    existingEmptyState.remove();
  }

  if (activeProfile && elements.chatWindow) {
    const valuesHtml = (activeProfile.values || []).map(v => `<span class="value-chip">${v.value}</span>`).join(' ');
    const promptsHtml = (activeProfile.example_prompts || []).map(p => `<button class="example-prompt-btn">"${p}"</button>`).join('');
    const descriptionHtml = activeProfile.description 
      ? `<p class="text-base text-neutral-600 dark:text-neutral-300 mt-4 max-w-md mx-auto">${activeProfile.description}</p>`
      : '';

    const emptyStateContainer = document.createElement('div');
    emptyStateContainer.className = 'empty-state-container';
    emptyStateContainer.innerHTML = `<div class="text-center pt-8">
        <p class="text-lg text-neutral-500 dark:text-neutral-400">SAFi is currently set with the</p>
        <h2 class="text-2xl font-semibold my-2">${activeProfile.name || 'Default'}</h2>
        <p class="text-sm text-neutral-500 dark:text-neutral-400">persona, which includes these values:</p>
        <div class="flex flex-wrap justify-center gap-2 my-4 max-w-md mx-auto">${valuesHtml}</div>
        ${descriptionHtml}
         <div class="mt-6 text-sm text-neutral-700 dark:text-neutral-300">
            To choose a different persona, click the <svg class="inline-block w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0 3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg> settings gear and select from the dropdown.
        </div>
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-6 mb-3">To begin, type below or pick an example prompt:</p>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 max-w-4xl mx-auto">${promptsHtml}</div>
      </div>`;
    
    elements.chatWindow.appendChild(emptyStateContainer);

    emptyStateContainer.querySelectorAll('.example-prompt-btn').forEach(btn => {
        btn.addEventListener('click', () => promptClickHandler(btn.textContent.replace(/"/g, '')));
    });
  }
}

export function resetChatView() {
  lastRenderedDay = '';
  while (elements.chatWindow.firstChild) {
    elements.chatWindow.removeChild(elements.chatWindow.firstChild);
  }
}

export function setActiveConvoLink(id) {
  document.querySelectorAll('#convo-list > a').forEach(link => {
    const isActive = link.dataset.id === String(id);
    link.classList.toggle('bg-green-100', isActive);
    link.classList.toggle('dark:bg-green-900/50', isActive);
    link.classList.toggle('text-green-800', isActive);
    link.classList.toggle('dark:text-green-300', isActive);
    link.classList.toggle('font-medium', isActive);
  });
}
