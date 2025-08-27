import { formatTime } from './utils.js';

export const elements = {
  loginView: document.getElementById('login-view'),
  chatView: document.getElementById('chat-view'),
  loginButton: document.getElementById('login-button'),
  userProfileContainer: document.getElementById('user-profile-container'),
  chatWindow: document.getElementById('chat-window'),
  messageInput: document.getElementById('message-input'),
  sendButton: document.getElementById('send-button'),
  sidebar: document.getElementById('sidebar'),
  newChatButton: document.getElementById('new-chat-button'),
  convoList: document.getElementById('convo-list'),
  chatTitle: document.getElementById('chat-title'),
  menuToggle: document.getElementById('menu-toggle'),
  closeSidebarButton: document.getElementById('close-sidebar-button'),
  sidebarOverlay: document.getElementById('sidebar-overlay'),
  emptyState: document.getElementById('empty-state'),
  activeProfileDisplay: document.getElementById('active-profile-display'),
  toastContainer: document.getElementById('toast-container'),
  modalBackdrop: document.getElementById('modal-backdrop'),
  conscienceModal: document.getElementById('conscience-modal'),
  deleteAccountModal: document.getElementById('delete-account-modal'),
  composerFooter: document.getElementById('composer-footer'),
  closeConscienceModalBtn: document.getElementById('close-conscience-modal'),
  cancelDeleteBtn: document.getElementById('cancel-delete-btn'),
  confirmDeleteBtn: document.getElementById('confirm-delete-btn'),
  conscienceDetails: document.getElementById('conscience-details'),
};

let activeToast = null;
let lastRenderedDay = '';

export function openSidebar() {
  elements.sidebar.classList.remove('-translate-x-full');
  elements.sidebarOverlay.classList.remove('hidden');
}

export function closeSidebar() {
  elements.sidebar.classList.add('-translate-x-full');
  elements.sidebarOverlay.classList.add('hidden');
}

export function updateUIForAuthState(user, logoutHandler, profileChangeHandler) {
  if (user) {
    elements.loginView.classList.add('hidden');
    elements.sidebar.classList.remove('hidden');
    elements.sidebar.classList.add('md:flex');
    elements.chatView.classList.remove('hidden');

    const pic = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;
    const name = user.name || user.email || 'User';
    
    elements.userProfileContainer.innerHTML = `
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
            <svg class="w-5 h-5 text-neutral-500 dark:text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
          </button>
          <div id="settings-dropdown" class="absolute bottom-full right-0 mb-2 w-48 bg-white dark:bg-neutral-800 rounded-lg shadow-xl border border-neutral-200 dark:border-neutral-700 hidden z-10">
            <div class="p-2">
              <label for="profile-selector" class="block text-xs font-medium text-neutral-500 dark:text-neutral-400 px-2 mb-1">Active Value Set</label>
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
    elements.userProfileContainer.innerHTML = '';
    elements.loginView.classList.remove('hidden');
    elements.sidebar.classList.add('hidden');
    elements.sidebar.classList.remove('md:flex');
    elements.chatView.classList.add('hidden');
  }
}

export function populateProfileSelector(profiles, selectedProfile) {
    const selector = document.getElementById('profile-selector');
    if (!selector) return;
    selector.innerHTML = '';
    profiles.forEach(profile => {
        const option = document.createElement('option');
        option.value = profile;
        option.textContent = profile.charAt(0).toUpperCase() + profile.slice(1);
        option.selected = profile === selectedProfile;
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
  elements.convoList.appendChild(link);
}

export function displayMessage(sender, text, date = new Date(), messageId = null, payload = null, whyHandler = null) {
  elements.emptyState.classList.add('hidden');
  maybeInsertDayDivider(date);

  const messageContainer = document.createElement('div');
  messageContainer.className = 'message-container';
  if (messageId) {
    messageContainer.dataset.messageId = messageId;
  }

  const messageDiv = document.createElement('div');
  messageDiv.className = `message ${sender}`;

  const html = DOMPurify.sanitize(marked.parse(text ?? ''));

  const contentDiv = document.createElement('div');
  contentDiv.className = 'chat-bubble';
  contentDiv.innerHTML = html;

  const metaDiv = document.createElement('div');
  metaDiv.className = 'meta';

  const stampDiv = document.createElement('div');
  stampDiv.className = 'stamp';
  stampDiv.textContent = formatTime(date);

  const hasLedger = payload && Array.isArray(payload.ledger) && payload.ledger.length > 0;
  if (hasLedger && whyHandler) {
      const whyButton = document.createElement('button');
      whyButton.className = 'why-btn';
      whyButton.textContent = 'Why this answer?';
      whyButton.addEventListener('click', () => whyHandler(payload));
      metaDiv.appendChild(whyButton);
  } else {
      const placeholder = document.createElement('div');
      metaDiv.appendChild(placeholder);
  }

  metaDiv.appendChild(stampDiv);

  messageDiv.appendChild(contentDiv);

  if (sender === 'ai') {
      messageDiv.classList.add('group', 'relative');
      messageDiv.appendChild(makeCopyButton(text));
  }

  messageDiv.appendChild(metaDiv);
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
        whyButton.textContent = 'Why this answer?';
        whyButton.addEventListener('click', () => whyHandler(payload));
        
        metaDiv.insertBefore(whyButton, metaDiv.firstChild);
    }
}

// CHANGE: Updated to use the new thinking spinner
export function showLoadingIndicator() {
  elements.emptyState.classList.add('hidden');
  maybeInsertDayDivider(new Date());
  const loadingContainer = document.createElement('div');
  loadingContainer.className = 'message-container';
  loadingContainer.innerHTML = `
    <div class="message ai">
        <div class="flex items-center gap-3">
          <div class="thinking-spinner"></div>
          <span id="thinking-status" class="text-gray-500 dark:text-gray-400 italic">Thinking...</span>
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

export function showModal(kind, data) {
  if (kind === 'conscience') {
    const payload = data || { ledger: [], profile: null, values: [], spirit_score: null };
    const box = document.getElementById('conscience-details');
    if (!box) return;
    box.innerHTML = '';
    renderConscienceHeader(box, payload);
    renderConscienceLedger(box, payload.ledger);
    elements.conscienceModal.classList.remove('hidden');
    elements.modalBackdrop.classList.remove('hidden');
  } else if (kind === 'delete') {
    elements.deleteAccountModal.classList.remove('hidden');
    elements.modalBackdrop.classList.remove('hidden');
  }
}

function renderConscienceHeader(container, payload) {
  const name = payload.profile || 'Current value set';
  const chips = (payload.values || []).map(v => `<span class="px-2 py-1 rounded-full border border-neutral-300 dark:border-neutral-700 text-sm">${v.value} <span class="text-neutral-500">(${Math.round((v.weight || 0) * 100)}%)</span></span>`).join(' ');
  let scoreHtml = '';
  if (payload.spirit_score !== null && payload.spirit_score !== undefined) {
    const score = Math.max(1, Math.min(10, payload.spirit_score));
    const scorePercentage = (score - 1) / 9 * 100;
    scoreHtml = `<div class="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3 my-4">
        <div class="flex items-center justify-between mb-1"><div class="text-sm font-semibold">Alignment Score</div><div class="text-lg font-bold text-emerald-600 dark:text-emerald-400">${score}/10</div></div>
        <div class="w-full bg-neutral-200 dark:bg-neutral-700 rounded-full h-2.5"><div class="bg-emerald-500 h-2.5 rounded-full" style="width: ${scorePercentage}%"></div></div>
        <p class="text-xs text-neutral-500 dark:text-neutral-400 mt-1.5">This score reflects alignment with the active value set.</p>
      </div>`;
  }
  container.innerHTML = `<div class="mb-4"><div class="text-xs uppercase tracking-wide text-neutral-500">Value Set:</div><div class="text-base font-semibold">${name}</div><div class="mt-2 flex flex-wrap gap-2">${chips || '—'}</div></div>${scoreHtml}`;
}

function renderConscienceLedger(container, ledger) {
  const html = (ledger || []).map(row => {
    const s = Number(row.score ?? 0);
    const bucket = s > 0 ? 'uphold' : s < 0 ? 'conflict' : 'neutral';
    const tone = {
      uphold: { icon: '▲', pill: 'text-green-700 bg-green-50 dark:text-green-300 dark:bg-green-900/30', title: 'text-green-700 dark:text-green-300', label: 'Upholds' },
      conflict: { icon: '▼', pill: 'text-red-700 bg-red-50 dark:text-red-300 dark:bg-red-900/30', title: 'text-red-700 dark:text-red-300', label: 'Conflicts with' },
      neutral: { icon: '•', pill: 'text-neutral-600 bg-neutral-100 dark:text-neutral-300 dark:bg-neutral-800', title: 'text-neutral-800 dark:text-neutral-200', label: 'Neutral on' }
    }[bucket];
    return `<div class="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3 mb-3">
        <div class="flex items-center gap-2 mb-1"><span class="inline-flex items-center justify-center w-5 h-5 rounded-full ${tone.pill} text-xs">${tone.icon}</span><div class="font-semibold ${tone.title}">${tone.label} ${row.value}</div></div>
        <div class="text-sm text-neutral-600 dark:text-neutral-400">${DOMPurify.sanitize(String(row.reason || ''))}</div>
      </div>`;
  }).join('');
  container.insertAdjacentHTML('beforeend', html || '<div class="text-sm text-neutral-500">No ledger available.</div>');
}

export function closeModal() {
  elements.modalBackdrop.classList.add('hidden');
  elements.conscienceModal.classList.add('hidden');
  elements.deleteAccountModal.classList.add('hidden');
}

export function scrollToBottom() {
  requestAnimationFrame(() => { elements.chatWindow.scrollTop = elements.chatWindow.scrollHeight; });
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
  btn.className = 'absolute top-2 right-2 bg-neutral-200 dark:bg-neutral-700 text-xs px-2 py-1 rounded-md hover:bg-neutral-300 dark:hover:bg-neutral-600 opacity-0 group-hover:opacity-100 transition-opacity';
  btn.textContent = 'Copy';
  btn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = 'Copied!';
      showToast('Copied to clipboard', 'success');
    } catch (err) {
      showToast('Failed to copy', 'error');
    }
    setTimeout(() => btn.textContent = 'Copy', 1500);
  });
  return btn;
}

export function displayEmptyState(activeProfile, promptClickHandler) {
  if (activeProfile && elements.activeProfileDisplay) {
    const valuesHtml = (activeProfile.values || []).map(v => `<span class="value-chip">${v.value}</span>`).join(' ');
    const promptsHtml = (activeProfile.example_prompts || []).map(p => `<button class="example-prompt-btn">"${p}"</button>`).join('');
    elements.activeProfileDisplay.innerHTML = `<div class="text-center pt-8">
        <p class="text-lg text-neutral-500 dark:text-neutral-400">SAFi is operating with the</p>
        <h2 class="text-2xl font-semibold my-2">${activeProfile.name || 'Default'}</h2>
        <p class="text-sm text-neutral-500 dark:text-neutral-400">value set, which includes:</p>
        <div class="flex flex-wrap justify-center gap-2 my-4 max-w-md mx-auto">${valuesHtml}</div>
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-6 mb-3">Try asking:</p>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 max-w-4xl mx-auto">${promptsHtml}</div>
      </div>`;
    document.querySelectorAll('.example-prompt-btn').forEach(btn => {
        btn.addEventListener('click', () => promptClickHandler(btn.textContent.replace(/"/g, '')));
    });
  }
  elements.emptyState.classList.remove('hidden');
}

export function resetChatView() {
  lastRenderedDay = '';
  Array.from(elements.chatWindow.children).forEach(child => {
    if (child.id !== 'empty-state') child.remove();
  });
  if(elements.activeProfileDisplay) elements.activeProfileDisplay.innerHTML = '';
  elements.emptyState.classList.add('hidden');
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
