// js/ui/render.js
// Handles creating and rendering HTML content into the DOM.

import { formatTime } from '../utils.js';
import { elements, scrollToBottom, openSidebar, closeSidebar } from './dom.js';
import { showToast, showModal } from './components.js';
import { eventHandlers } from '../events.js'; // Import handlers directly.

let lastRenderedDay = '';

function makeCopyButton(text) {
  const btn = document.createElement('button');
  btn.className = 'meta-btn';
  btn.title = 'Copy Text';
  btn.innerHTML = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>`;
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed"; 
    textArea.style.left = "-9999px";
    document.body.appendChild(textArea);
    textArea.select();
    try {
      document.execCommand('copy');
      showToast('Copied to clipboard', 'success');
    } catch (err) {
      showToast('Failed to copy', 'error');
    }
    document.body.removeChild(textArea);
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
  if (!chatWindow) return;

  if(emptyState) emptyState.classList.add('hidden');
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
    if (!chatWindow) return;
    maybeInsertDayDivider(new Date());

    const loadingContainer = document.createElement('div');
    loadingContainer.id = 'loading-indicator';
    loadingContainer.className = 'message-container';
    loadingContainer.innerHTML = `<div class="message ai"><div class="flex items-center gap-3"><div class="thinking-spinner"></div><span class="text-gray-500 dark:text-gray-400 italic">Thinking...</span></div></div>`;
    chatWindow.appendChild(loadingContainer);
    scrollToBottom();
    return loadingContainer;
}

export function renderConversationLink(convo) {
  const link = document.createElement('a');
  link.href = '#';
  link.dataset.id = convo.id;
  link.className = 'group flex items-center justify-between px-3 py-2 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-lg';
  link.innerHTML = `<span class="truncate">${convo.title || 'Untitled'}</span>
    <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <button data-action="rename" class="p-1 rounded-md" aria-label="Rename"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.5L15.232 5.232z"></path></svg></button>
      <button data-action="delete" class="p-1 rounded-md" aria-label="Delete"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-4v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg></button>
    </div>`;
  
  link.addEventListener('click', (e) => {
    e.preventDefault();
    const action = e.target.closest('button')?.dataset.action;
    if (action === 'rename') {
        eventHandlers.renameHandler(convo.id, convo.title || 'Untitled');
    } else if (action === 'delete') {
        eventHandlers.deleteHandler(convo.id);
    } else {
        eventHandlers.switchHandler(convo.id);
    }
  });

  return link;
}

export function displayEmptyStateForUser(activeProfile, promptClickHandler) {
    const activeProfileDisplay = elements.activeProfileDisplay();
    if (!activeProfile || !activeProfileDisplay) return;

    const valuesHtml = (activeProfile.values || []).map(v => `<span class="value-chip">${v.value}</span>`).join(' ');
    const promptsHtml = (activeProfile.example_prompts || []).map(p => `<button class="example-prompt-btn">"${p}"</button>`).join('');
    
    activeProfileDisplay.innerHTML = `<div class="text-center pt-8">
        <h2 class="text-2xl font-semibold my-2">New Chat</h2>
        <p class="text-base text-neutral-600 dark:text-neutral-300 mt-4 max-w-lg mx-auto">You're using the <strong>${activeProfile.name}</strong> ethical profile with the following values:</p>
        <div class="flex flex-wrap justify-center gap-2 my-4 max-w-md mx-auto">${valuesHtml}</div>
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-6 mb-3">To begin, type below or pick an example prompt:</p>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 max-w-4xl mx-auto">${promptsHtml}</div>
    </div>`;
    
    document.querySelectorAll('.example-prompt-btn').forEach(btn => {
        btn.addEventListener('click', () => promptClickHandler(btn.textContent.replace(/"/g, '')));
    });

    elements.emptyState()?.classList.remove('hidden');
}

export function displayGuestWelcome() {
    const activeProfileDisplay = elements.activeProfileDisplay();
    if (!activeProfileDisplay) return;

    activeProfileDisplay.innerHTML = `<div class="text-center pt-8">
        <div class="inline-block p-4 bg-green-100 dark:bg-green-900/50 rounded-full mb-4">
            <img src="assets/logo.png" alt="SAFi Logo" class="w-12 h-12 rounded-lg">
        </div>
        <h2 class="text-2xl font-semibold my-2">Welcome to SAFi</h2>
        <p class="text-base text-neutral-600 dark:text-neutral-300 mt-4 max-w-xl mx-auto">SAFi is an ethical reasoning engine. To start a conversation, save your history, and manage ethical profiles, please sign in.</p>
    </div>`;
    elements.emptyState()?.classList.remove('hidden');
}


export function renderSidebar(user, profiles, selectedKey) {
    const sidebarContainer = elements.sidebarContainer();
    if (!sidebarContainer) return;

    sidebarContainer.innerHTML = `
        <div id="sidebar-overlay" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-30 hidden md:hidden"></div>
        <aside id="sidebar" class="fixed inset-y-0 left-0 w-80 bg-white dark:bg-black text-neutral-900 dark:text-white flex flex-col z-40 transform -translate-x-full md:translate-x-0 h-full border-r border-gray-200 dark:border-gray-800">
          <div class="p-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between shrink-0">
            <div class="flex items-center gap-3"><div class="app-logo h-10 w-10"><img src="assets/logo.png" alt="SAFi Logo" class="rounded-lg w-full h-full"></div><div><h1 class="text-lg font-bold">SAFi</h1><p class="text-xs text-gray-500 dark:text-gray-400">The Ethical Reasoning Engine</p></div></div>
            <button id="close-sidebar-button" class="p-1 rounded-full md:hidden">X</button>
          </div>
          <div class="p-4 shrink-0"><button id="new-chat-button" class="w-full bg-green-600 text-white font-semibold px-4 py-2.5 rounded-lg hover:bg-green-700 flex items-center justify-center gap-2">New Chat</button></div>
          <nav id="convo-list" class="flex-1 overflow-y-auto p-2 space-y-1 min-h-0"></nav>
          <div id="user-profile-container" class="p-4 border-t border-gray-200 dark:border-gray-800 shrink-0"></div>
        </aside>`;

    const profileContainer = document.getElementById('user-profile-container');
    const convoList = document.getElementById('convo-list');

    if (user) {
        // Render logged-in user profile
        const pic = user.picture || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;
        profileContainer.innerHTML = `
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-3 min-w-0"><img src="${pic}" alt="User Avatar" class="w-10 h-10 rounded-full"><div class="flex-1 min-w-0"><p class="text-sm font-semibold truncate">${user.name}</p><p class="text-xs truncate">${user.email}</p></div></div>
            <div class="relative" id="settings-menu">
              <button id="settings-button" class="p-2 rounded-full"><svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0 3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg></button>
              <div id="settings-dropdown" class="absolute bottom-full right-0 mb-2 w-48 bg-white dark:bg-neutral-800 rounded-lg shadow-xl border hidden z-10">
                <div class="p-2"><label class="block text-xs px-2 mb-1">Active Profile</label><select id="profile-selector" class="w-full text-sm rounded-md py-1.5 px-2"></select></div>
                <div class="border-t my-1"></div>
                <button id="theme-toggle" class="flex items-center gap-2 w-full text-left px-4 py-2 text-sm">Toggle Theme</button>
                <div class="border-t my-1"></div>
                <button id="logout-button" class="w-full text-left px-4 py-2 text-sm">Sign Out</button>
                <button id="delete-account-btn" class="w-full text-left px-4 py-2 text-sm text-red-600">Delete Account</button>
              </div>
            </div>
          </div>`;
        populateProfileSelector(profiles, selectedKey);

        // --- Attach Logged-in specific listeners ---
        document.getElementById('logout-button')?.addEventListener('click', eventHandlers.logoutHandler);
        document.getElementById('delete-account-btn')?.addEventListener('click', () => showModal('delete'));
        document.getElementById('profile-selector')?.addEventListener('change', eventHandlers.profileChangeHandler);
        document.getElementById('theme-toggle')?.addEventListener('click', () => {
            document.documentElement.classList.toggle('dark');
            localStorage.theme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
        });
        const settingsButton = document.getElementById('settings-button');
        const settingsDropdown = document.getElementById('settings-dropdown');
        settingsButton?.addEventListener('click', (event) => {
            event.stopPropagation();
            settingsDropdown?.classList.toggle('hidden');
        });

    } else {
        // Render guest profile/login prompt
        convoList.innerHTML = `<div class="px-3 py-2 text-sm text-neutral-500">Sign in to view your conversation history.</div>`;
        profileContainer.innerHTML = `
            <div>
                <p class="text-sm text-neutral-600 dark:text-neutral-300 mb-3">Sign in to save chats and manage ethical profiles.</p>
                <button id="sidebar-login-button" class="w-full bg-green-600 text-white font-semibold px-4 py-2.5 rounded-lg hover:bg-green-700 flex items-center justify-center gap-2">
                    <svg class="w-5 h-5" viewBox="0 0 48 48" fill="none" stroke="currentColor"><path d="M43.611,20.083H42V20H24v8h11.303c-1.649,4.657-6.08,8-11.303,8c-6.627,0-12-5.373-12-12c0-6.627,5.373-12,12-12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C16.318,4,9.656,8.337,6.306,14.691z" fill="#FFC107"></path><path d="M6.306,14.691l6.571,4.819C14.655,15.108,18.961,12,24,12c3.059,0,5.842,1.154,7.961,3.039l5.657-5.657C34.046,6.053,29.268,4,24,4C16.318,4,9.656,8.337,6.306,14.691z" fill="#FF3D00"></path><path d="M24,44c5.166,0,9.86-1.977,13.409-5.192l-6.19-5.238C29.211,35.091,26.715,36,24,36c-5.202,0-9.619-3.317-11.283-7.946l-6.522,5.025C9.505,39.556,16.227,44,24,44z" fill="#4CAF50"></path><path d="M43.611,20.083H42V20H24v8h11.303c-0.792,2.237-2.231,4.166-4.082,5.571l6.19,5.238C42.021,35.596,44,30.138,44,24C44,22.659,43.862,21.35,43.611,20.083z" fill="#1976D2"></path></svg>
                    Sign in with Google
                </button>
            </div>`;
        // --- Attach Guest specific listeners ---
         document.getElementById('sidebar-login-button')?.addEventListener('click', eventHandlers.loginHandler);
    }
    
    // --- Attach listeners common to both states ---
    document.getElementById('new-chat-button')?.addEventListener('click', eventHandlers.newChatHandler);
    document.getElementById('close-sidebar-button')?.addEventListener('click', closeSidebar);
    document.getElementById('sidebar-overlay')?.addEventListener('click', closeSidebar);
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

