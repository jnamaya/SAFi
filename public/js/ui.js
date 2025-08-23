import { formatTime /*, escapeHtml if you add it later */ } from './utils.js';

export const elements = {
  loginView: document.getElementById('login-view'),
  chatView: document.getElementById('chat-view'),
  loginButton: document.getElementById('login-button'),
  userProfileSidebar: document.getElementById('user-profile-sidebar'),
  chatWindow: document.getElementById('chat-window'),
  messageInput: document.getElementById('message-input'),
  sendButton: document.getElementById('send-button'),
  themeToggle: document.getElementById('theme-toggle'),
  themeIconLight: document.getElementById('theme-icon-light'),
  themeIconDark: document.getElementById('theme-icon-dark'),
  sidebar: document.getElementById('sidebar'),
  newChatButton: document.getElementById('new-chat-button'),
  convoList: document.getElementById('convo-list'),
  chatTitle: document.getElementById('chat-title'),
  menuToggle: document.getElementById('menu-toggle'),
  closeSidebarButton: document.getElementById('close-sidebar-button'),
  sidebarOverlay: document.getElementById('sidebar-overlay'),
  emptyState: document.getElementById('empty-state'),
  activeProfileDisplay: document.getElementById('active-profile-display'),
  connectionStatusDot: document.getElementById('connection-status-dot'),
  connectionStatusText: document.getElementById('connection-status-text'),
  toastContainer: document.getElementById('toast-container'),
  modalBackdrop: document.getElementById('modal-backdrop'),
  conscienceModal: document.getElementById('conscience-modal'),
  deleteAccountModal: document.getElementById('delete-account-modal'),
  composerFooter: document.getElementById('composer-footer'),
  closeConscienceModalBtn: document.getElementById('close-conscience-modal'),
  // CHANGE: Added the new mobile close button
  mobileCloseConscienceModalBtn: document.getElementById('mobile-close-conscience-modal'),
  cancelDeleteBtn: document.getElementById('cancel-delete-btn'),
  confirmDeleteBtn: document.getElementById('confirm-delete-btn'),
  conscienceDetails: document.getElementById('conscience-details'),
};

let activeToast = null;
let lastRenderedDay = '';

export function updateThemeUI() {
  const isDark = document.documentElement.classList.contains('dark');
  if (elements.themeIconLight && elements.themeIconDark) {
    elements.themeIconLight.style.display = isDark ? 'none' : 'block';
    elements.themeIconDark.style.display = isDark ? 'block' : 'none';
  }
}

export function openSidebar() {
  elements.sidebar.classList.remove('-translate-x-full');
  elements.sidebarOverlay.classList.remove('hidden');
}

export function closeSidebar() {
  elements.sidebar.classList.add('-translate-x-full');
  elements.sidebarOverlay.classList.add('hidden');
}

export function updateUIForAuthState(user, logoutHandler) {
  if (user) {
    elements.loginView.classList.add('hidden');
    elements.sidebar.classList.remove('hidden');
    elements.sidebar.classList.add('md:flex');
    elements.chatView.classList.remove('hidden');

    const pic = user.picture || user.avatar || 'https://placehold.co/32x32';
    const name = user.name || user.email || 'User';
    elements.userProfileSidebar.innerHTML = `
      <div class="flex items-center gap-3">
        <img src="${pic}" alt="User profile" class="w-8 h-8 rounded-full" />
        <div class="flex-1 min-w-0">
          <p class="text-sm font-semibold truncate">${name}</p>
          <p class="text-xs text-neutral-500 truncate">${user.email}</p>
        </div>
      </div>
      <div class="mt-4 flex items-center justify-between text-sm">
      <button id="delete-account-btn" class="font-semibold text-red-600 dark:text-red-500 hover:underline">Delete</button>
        <button id="logout-button" class="font-semibold text-neutral-500 hover:text-black dark:hover:text-white">Sign Out</button>
      </div>`;
    document.getElementById('logout-button').addEventListener('click', logoutHandler);
    document.getElementById('delete-account-btn').addEventListener('click', () => showModal('delete'));
  } else {
    elements.loginView.classList.remove('hidden');
    elements.sidebar.classList.add('hidden');
    elements.sidebar.classList.remove('md:flex');
    elements.chatView.classList.add('hidden');
  }
}

export function renderConversationLink(convo, switchHandler, optionsHandler) {
  const convoContainer = document.createElement('div');
  convoContainer.className = 'group flex items-center rounded-lg';
  convoContainer.dataset.id = convo.id;

  const link = document.createElement('button');
  link.className = 'flex-1 text-left px-3 py-2 text-sm truncate';
  link.textContent = convo.title || 'Untitled';
  link.addEventListener('click', () => switchHandler(convo.id));

  const optionsBtn = document.createElement('button');
  optionsBtn.className = 'p-2 rounded-lg opacity-0 group-hover:opacity-100 hover:bg-neutral-300 dark:hover:bg-neutral-700';
  optionsBtn.innerHTML = '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z"/></svg>';
  optionsBtn.addEventListener('click', (e) => optionsHandler(e, convo.id, convo.title || 'Untitled'));

  convoContainer.appendChild(link);
  convoContainer.appendChild(optionsBtn);
  elements.convoList.appendChild(convoContainer);
}

export function displayMessage(sender, text, date = new Date(), payloadOrLedger = null, whyHandler) {
  elements.emptyState.classList.add('hidden');
  maybeInsertDayDivider(date);

  const container = document.createElement('div');
  const html = DOMPurify.sanitize(marked.parse(text ?? ''));

  const style = `style="font-size: 0.75rem; margin-top: 0.35rem;"`;

  const isArray = Array.isArray(payloadOrLedger);
  const payload = isArray
    ? { ledger: payloadOrLedger }
    : (payloadOrLedger || { ledger: [] });

  const hasLedger = Array.isArray(payload.ledger) && payload.ledger.length > 0;

  if (sender === 'user') {
    container.className = 'flex justify-end';
    container.innerHTML = `<div class="msg bg-green-600 text-white px-5 py-3 rounded-2xl rounded-br-none shadow-md chat-bubble">${html}<div class="stamp text-white/80" ${style}>${formatTime(date)}</div></div>`;
  } else {
    container.className = 'flex items-start gap-3 group';
    const whyButtonHtml = hasLedger ? `<button class="why-btn text-xs text-green-600 dark:text-green-500 font-semibold hover:underline mt-2">Why this answer?</button>` : '';
    container.innerHTML = `
      <img src="assets/logo.png" alt="SAFi Logo" class="h-10 w-10 rounded-lg flex-shrink-0" onerror="this.onerror=null; this.src='https://placehold.co/40x40/000000/FFFFFF?text=SAFi'"/>
      <div class="relative msg bg-neutral-100 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 px-5 py-3 rounded-2xl rounded-tl-none shadow-sm">
        <div class="chat-bubble">${html}</div>
        <div class="flex items-center justify-between">
          ${whyButtonHtml}
          <div class="stamp text-neutral-500 dark:text-neutral-400" ${style}>${formatTime(date)}</div>
        </div>
      </div>`;

    const bubble = container.querySelector('.msg');
    bubble.appendChild(makeCopyButton(text));
    if (hasLedger) {
      container.querySelector('.why-btn')?.addEventListener('click', () => whyHandler(payload));
    }
  }

  elements.chatWindow.appendChild(container);
  scrollToBottom();
  return container;
}

export function showLoadingIndicator() {
  elements.emptyState.classList.add('hidden');
  maybeInsertDayDivider(new Date());
  const loadingContainer = document.createElement('div');
  loadingContainer.className = 'flex items-start gap-3';
  loadingContainer.innerHTML = `
    <img src="assets/logo.png" alt="SAFi Logo" class="h-10 w-10 rounded-lg flex-shrink-0" onerror="this.onerror=null; this.src='https://placehold.co/40x40/000000/FFFFFF?text=SAFi'"/>
    <div class="bg-neutral-100 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 px-5 py-3 rounded-2xl rounded-tl-none flex items-center gap-1">
      <div class="w-2 h-2 bg-neutral-500 rounded-full animate-pulse"></div>
      <div class="w-2 h-2 bg-neutral-500 rounded-full animate-pulse" style="animation-delay:.2s"></div>
      <div class="w-2 h-2 bg-neutral-500 rounded-full animate-pulse" style="animation-delay:.4s"></div>
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

export function updateConnectionStatus(isOnline) {
  if (isOnline) {
    elements.connectionStatusDot.className = 'w-2 h-2 rounded-full bg-green-500';
    elements.connectionStatusText.textContent = 'Connected';
  } else {
    elements.connectionStatusDot.className = 'w-2 h-2 rounded-full bg-red-500';
    elements.connectionStatusText.textContent = 'Offline';
  }
}

export function showModal(kind, data) {
  if (kind === 'conscience') {
    const payload = Array.isArray(data)
      ? { ledger: data, profile: null, values: [] }
      : (data || { ledger: [], profile: null, values: [] });

    const box = document.getElementById('conscience-details');
    const modal = document.getElementById('conscience-modal');
    const backdrop = document.getElementById('modal-backdrop');
    if (!box || !modal || !backdrop) return;

    box.innerHTML = '';
    renderConscienceHeader(box, payload.profile, payload.values);
    renderConscienceLedger(box, payload.ledger);

    backdrop.classList.remove('hidden');
    modal.classList.remove('hidden');
    return;
  }
}

function renderConscienceHeader(container, profileName, values) {
  const name = profileName || 'Current value set';
  const chips = (values || []).map(v => (
    `<span class="px-2 py-1 rounded-full border border-neutral-300 dark:border-neutral-700 text-sm">
       ${v.value} <span class="text-neutral-500">(${Math.round((v.weight || 0) * 100)}%)</span>
     </span>`
  )).join(' ');

  const html = `
    <div class="mb-4">
      <div class="text-xs uppercase tracking-wide text-neutral-500">Active value set</div>
      <div class="text-base font-semibold">${name}</div>
      <div class="mt-2 flex flex-wrap gap-2">${chips || '—'}</div>
    </div>
  `;
  container.insertAdjacentHTML('afterbegin', html);
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
    const reason = row.reason ? DOMPurify.sanitize(String(row.reason)) : '';
    return `
      <div class="rounded-lg border border-neutral-200 dark:border-neutral-800 p-3 mb-3">
        <div class="flex items-center gap-2 mb-1">
          <span class="inline-flex items-center justify-center w-5 h-5 rounded-full ${tone.pill} text-xs">${tone.icon}</span>
          <div class="font-semibold ${tone.title}">${tone.label} ${row.value}</div>
        </div>
        <div class="text-sm text-neutral-600 dark:text-neutral-400">${reason}</div>
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

export function displayEmptyState(activeProfile) {
  if (activeProfile && elements.activeProfileDisplay) {
    const valuesHtml = (activeProfile.values || [])
      .map(v => `<span class="inline-block bg-neutral-200 dark:bg-neutral-700 rounded-full px-3 py-1 text-xs font-semibold text-neutral-700 dark:text-neutral-200">${v.value}</span>`)
      .join(' ');

    elements.activeProfileDisplay.innerHTML = `
      <p class="text-neutral-500 dark:text-neutral-400 mb-2">Using value set:</p>
      <div class="font-semibold text-base mb-3">${activeProfile.current || 'Default'}</div>
      <div class="flex flex-wrap justify-center gap-2 max-w-md mx-auto">${valuesHtml}</div>
    `;
  }
  elements.emptyState.classList.remove('hidden');
}

export function resetChatView() {
  lastRenderedDay = '';
  elements.chatWindow.innerHTML = '';
  if(elements.activeProfileDisplay) elements.activeProfileDisplay.innerHTML = '';
  elements.emptyState.classList.add('hidden');
}

export function setActiveConvoLink(id) {
  document.querySelectorAll('#convo-list > div').forEach(div => {
    div.classList.toggle('bg-green-100', div.dataset.id === String(id));
    div.classList.toggle('dark:bg-green-900', div.dataset.id === String(id));
  });
}
