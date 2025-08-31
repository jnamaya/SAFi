// js/ui/render.js
// Handles creating and rendering HTML content into the DOM.

import { formatTime } from '../utils.js';
import { elements, scrollToBottom } from './dom.js';
import { showToast, showModal } from './components.js';

let lastRenderedDay = '';

function makeCopyButton(text) {
  const btn = document.createElement('button');
  btn.className = 'meta-btn';
  btn.title = 'Copy Text';
  btn.innerHTML = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>`;
  btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    try {
      // Using document.execCommand for broader compatibility in sandboxed environments
      const textArea = document.createElement("textarea");
      textArea.value = text;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
      showToast('Copied to clipboard', 'success');
    } catch (err) {
      showToast('Failed to copy', 'error');
    }
  });
  return btn;
}

function maybeInsertDayDivider(date) {
  const key = date.toLocaleDateString();
  if (key !== lastRenderedDay) {
    lastRenderedDay = key;
    const div = document.createElement('div');
    div.className = 'flex items-center justify-center my-2';
    div.innerHTML = `<div class="text-xs text-neutral-500 dark:text-neutral-400 px-3 py-1 rounded-full bg-neutral-100 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700">${date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}</div>`;
    elements.chatWindow()?.appendChild(div);
  }
}

export function displayMessage(sender, text, date = new Date(), messageId = null, payload = null, whyHandler = null) {
  const chatWindow = elements.chatWindow();
  const emptyState = elements.emptyState();
  if (!chatWindow || !emptyState) return;

  emptyState.classList.add('hidden');
  maybeInsertDayDivider(date);

  const messageContainer = document.createElement('div');
  messageContainer.className = 'message-container';
  if (messageId) messageContainer.dataset.messageId = messageId;

  const messageDiv = document.createElement('div');
  messageDiv.className = `message ${sender}`;

  const html = DOMPurify.sanitize(marked.parse(text ?? ''));
  const contentDiv = document.createElement('div');
  contentDiv.className = 'chat-bubble';
  contentDiv.innerHTML = html;

  const metaDiv = document.createElement('div');
  metaDiv.className = 'meta';

  const hasLedger = payload && Array.isArray(payload.ledger) && payload.ledger.length > 0;
  if (hasLedger && whyHandler) {
      const whyButton = document.createElement('button');
      whyButton.className = 'why-btn';
      whyButton.textContent = 'Why this answer?';
      whyButton.addEventListener('click', () => whyHandler(payload));
      metaDiv.appendChild(whyButton);
  }

  const rightMeta = document.createElement('div');
  rightMeta.className = 'flex items-baseline gap-3 ml-auto';
  if (sender === 'ai') rightMeta.appendChild(makeCopyButton(text));
  
  const stampDiv = document.createElement('div');
  stampDiv.className = 'stamp';
  stampDiv.textContent = formatTime(date);
  rightMeta.appendChild(stampDiv);
  
  metaDiv.appendChild(rightMeta);
  messageDiv.appendChild(contentDiv);
  messageDiv.appendChild(metaDiv);
  messageContainer.appendChild(messageDiv);

  chatWindow.appendChild(messageContainer);
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


export function showLoadingIndicator() {
    const chatWindow = elements.chatWindow();
    const emptyState = elements.emptyState();
    if (!chatWindow || !emptyState) return;
    
    emptyState.classList.add('hidden');
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
    chatWindow.appendChild(loadingContainer);
    scrollToBottom();
    return loadingContainer;
}

export function renderConversationLink(convo, handlers) {
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
    if (action === 'rename') handlers.renameHandler(convo.id, convo.title || 'Untitled');
    else if (action === 'delete') handlers.deleteHandler(convo.id);
    else handlers.switchHandler(convo.id);
  });
  return link;
}

export function displayEmptyState(activeProfile, promptClickHandler) {
    const activeProfileDisplay = elements.activeProfileDisplay();
    if (!activeProfile || !activeProfileDisplay) return;

    const valuesHtml = (activeProfile.values || []).map(v => `<span class="value-chip">${v.value}</span>`).join(' ');
    const promptsHtml = (activeProfile.example_prompts || []).map(p => `<button class="example-prompt-btn">"${p}"</button>`).join('');
    const descriptionHtml = activeProfile.description ? `<p class="text-base text-neutral-600 dark:text-neutral-300 mt-4 max-w-md mx-auto">${activeProfile.description}</p>` : '';

    activeProfileDisplay.innerHTML = `<div class="text-center pt-8">
        <p class="text-lg text-neutral-500 dark:text-neutral-400">SAFi is currently set with the</p>
        <h2 class="text-2xl font-semibold my-2">${activeProfile.name || 'Default'}</h2>
        <p class="text-sm text-neutral-500 dark:text-neutral-400">ethical profile, which includes these values:</p>
        <div class="flex flex-wrap justify-center gap-2 my-4 max-w-md mx-auto">${valuesHtml}</div>
        ${descriptionHtml}
        <div class="mt-6 text-sm text-neutral-700 dark:text-neutral-300">To choose a different profile, click the settings gear.</div>
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-6 mb-3">To begin, type below or pick an example prompt:</p>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 max-w-4xl mx-auto">${promptsHtml}</div>
    </div>`;
    
    document.querySelectorAll('.example-prompt-btn').forEach(btn => {
        btn.addEventListener('click', () => promptClickHandler(btn.textContent.replace(/"/g, '')));
    });

    elements.emptyState()?.classList.remove('hidden');
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

export function renderAuthenticatedUI(user, profiles, selectedKey) {
    const sidebarContainer = elements.sidebarContainer();
    if (!sidebarContainer) return;

    sidebarContainer.innerHTML = `
        <div id="sidebar-overlay" class="fixed inset-0 bg-black/50 z-30 hidden md:hidden"></div>
        <aside id="sidebar" class="fixed inset-y-0 left-0 w-80 bg-white dark:bg-black text-neutral-900 dark:text-white flex flex-col z-40 transform -translate-x-full transition-transform duration-300 ease-in-out md:translate-x-0 h-full border-r border-gray-200 dark:border-gray-800">
          <div class="p-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between shrink-0">
            <div class="flex items-center gap-3">
              <div class="app-logo h-10 w-10"><img src="assets/logo.png" alt="SAFi Logo" class="rounded-lg w-full h-full"></div>
              <div>
                <h1 class="text-lg font-bold">SAFi</h1>
                <p class="text-xs text-gray-500 dark:text-gray-400">The Ethical Reasoning Engine</p>
              </div>
            </div>
            <button id="close-sidebar-button" type="button" aria-label="Close sidebar" class="p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 md:hidden">
              <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>
          <div class="p-4 shrink-0">
            <button id="new-chat-button" type="button" class="w-full bg-green-600 text-white font-semibold px-4 py-2.5 rounded-lg hover:bg-green-700 transition-colors flex items-center justify-center gap-2 shadow-sm hover:shadow-md">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
              New Chat
            </button>
          </div>
          <nav id="convo-list" aria-label="Conversation history" class="flex-1 overflow-y-auto p-2 space-y-1 custom-scrollbar min-h-0">
            <h3 class="px-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">History</h3>
          </nav>
          <div id="user-profile-container" class="p-4 border-t border-gray-200 dark:border-gray-800 shrink-0"></div>
        </aside>`;
    
    const pic = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;
    const name = user.name || user.email || 'User';
    
    document.getElementById('user-profile-container').innerHTML = `
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3 min-w-0">
          <img src="${pic}" alt="User Avatar" class="w-10 h-10 rounded-full">
          <div class="flex-1 min-w-0"><p class="text-sm font-semibold truncate">${name}</p><p class="text-xs text-neutral-500 dark:text-neutral-400 truncate">${user.email}</p></div>
        </div>
        <div class="relative" id="settings-menu">
          <button id="settings-button" class="p-2 rounded-full hover:bg-neutral-100 dark:hover:bg-neutral-700"><svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0 3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg></button>
          <div id="settings-dropdown" class="absolute bottom-full right-0 mb-2 w-48 bg-white dark:bg-neutral-800 rounded-lg shadow-xl border hidden z-10">
            <div class="p-2">
              <label class="block text-xs font-medium px-2 mb-1">Active Ethical profile</label>
              <select id="profile-selector" class="w-full text-sm rounded-md py-1.5 px-2"></select>
            </div>
            <div class="border-t my-1"></div>
            <button id="theme-toggle" class="flex items-center gap-2 w-full text-left px-4 py-2 text-sm"><span>Toggle Theme</span></button>
            <div class="border-t my-1"></div>
            <button id="logout-button" class="block w-full text-left px-4 py-2 text-sm">Sign Out</button>
            <button id="delete-account-btn" class="block w-full text-left px-4 py-2 text-sm text-red-600">Delete Account</button>
          </div>
        </div>
      </div>`;
      
    populateProfileSelector(profiles, selectedKey);
    lastRenderedDay = ''; // Reset day divider on auth change
}
