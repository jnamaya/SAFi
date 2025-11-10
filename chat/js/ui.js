import { formatTime, formatRelativeTime } from './utils.js';

marked.setOptions({
  breaks: false, // Render <br> ONLY on double line breaks (standard Markdown)
  gfm: true,    // Use GitHub Flavored Markdown for tables, etc.
  mangle: false,
  headerIds: false,
  highlight: function(code, lang) {
    // Use highlight.js for syntax highlighting
    const language = hljs.getLanguage(lang) ? lang : 'plaintext';
    return hljs.highlight(code, { language }).value;
  }
});

/**
 * Maps a profile name to a static avatar image path.
 * All paths are relative to the 'assets/' folder.
 * @param {string | null} profileName The name of the ethical profile
 * @returns {string} The path to the avatar image
 */
function getAvatarForProfile(profileName) {
  // Use a simple name-to-file mapping
  // These names MUST match the "name" field in your values.py
  
  // MODIFICATION: Trim and convert to lower case for a robust, case-insensitive check
  const cleanName = profileName ? profileName.trim().toLowerCase() : null;

  switch (cleanName) {
    case 'the philosopher':
      return 'assets/philosopher.svg';
    case 'the fiduciary':
      return 'assets/fiduciary.svg';
    case 'the health navigator':
      return 'assets/health_navigator.svg';
    case 'the jurist':
      return 'assets/jurist.svg';
    case 'the bible scholar':
      return 'assets/bible_scholar.svg';
    case 'the safi guide':
    default:
      // Fallback for "The SAFi Guide", null, or unmatched profiles
      return 'assets/safi.svg';
  }
}

export let elements = {};
let currentLoadingInterval = null; // (Task 1)

// Initialization function to run after DOM is loaded
function _initElements() {
  elements = {
    loginView: document.getElementById('login-view'),
    chatView: document.getElementById('chat-view'),
    // MODIFICATION: 1.1. Added Control Panel View
    controlPanelView: document.getElementById('control-panel-view'),
    controlPanelBackButton: document.getElementById('control-panel-back-btn'),
    cpNavProfile: document.getElementById('cp-nav-profile'),
    cpNavModels: document.getElementById('cp-nav-models'),
    cpNavDashboard: document.getElementById('cp-nav-dashboard'),
    cpTabProfile: document.getElementById('cp-tab-profile'),
    cpTabModels: document.getElementById('cp-tab-models'),
    cpTabDashboard: document.getElementById('cp-tab-dashboard'),
    // MODIFICATION: 3.1. Added App Settings tab elements
    cpNavAppSettings: document.getElementById('cp-nav-app-settings'),
    cpTabAppSettings: document.getElementById('cp-tab-app-settings'),
    // END MODIFICATION

    loginButton: document.getElementById('login-button'),
    sidebarContainer: document.getElementById('sidebar-container'),
    chatWindow: document.getElementById('chat-window'),
    messageInput: document.getElementById('message-input'),
    sendButton: document.getElementById('send-button'),
    // chatTitle element removed from here, it's fetched in updateChatTitle
    toastContainer: document.getElementById('toast-container'),
    modalBackdrop: document.getElementById('modal-backdrop'),
    conscienceModal: document.getElementById('conscience-modal'),
    deleteAccountModal: document.getElementById('delete-account-modal'),
    composerFooter: document.getElementById('composer-footer'),
    conscienceDetails: document.getElementById('conscience-details'),
    closeConscienceModalBtn: document.getElementById('close-conscience-modal'),
    
    // MODIFICATION: 1.1. Removed Settings Modal elements
    // MODIFICATION: 1.2. Removed App Settings Modal elements (now part of CP)

    dashboardIframeContainer: document.getElementById('dashboard-iframe-container'), // This is inside cp-tab-dashboard now

    renameModal: document.getElementById('rename-modal'),
    renameInput: document.getElementById('rename-input'),
    confirmRenameBtn: document.getElementById('confirm-rename-btn'),
    cancelRenameBtn: document.getElementById('cancel-rename-btn'),

    deleteConvoModal: document.getElementById('delete-convo-modal'),
    confirmDeleteConvoBtn: document.getElementById('confirm-delete-convo-btn'),
    cancelDeleteConvoBtn: document.getElementById('cancel-delete-convo-btn'),

    // MODIFICATION: 1.3. Added Active Profile Chip elements
    activeProfileChip: document.getElementById('active-profile-chip'),
    activeProfileChipMobile: document.getElementById('active-profile-chip-mobile'),
    // END MODIFICATION
  };

  // MODIFICATION: 1.1. Removed dashboard back button listener (it's the main CP back button now)
}


let activeToast = null;
let lastRenderedDay = '';
let openDropdown = null;

// Helper to lazily initialize elements
function _ensureElements() {
  if (!elements.loginView) {
    _initElements();
  }
}

// Helper to close all conversation menus
export function closeAllConvoMenus() {
  if (openDropdown) {
    openDropdown.remove();
    openDropdown = null;
  }
}

export function openSidebar() {
  _ensureElements();
  document.getElementById('sidebar')?.classList.remove('-translate-x-full');
  document.getElementById('sidebar-overlay')?.classList.remove('hidden');
}

export function closeSidebar() {
  _ensureElements();
  document.getElementById('sidebar')?.classList.add('-translate-x-full');
  document.getElementById('sidebar-overlay')?.classList.add('hidden');
}

// *** (Task 1) This function is correct and unchanged ***
export function clearLoadingInterval() {
  if (currentLoadingInterval) {
    clearInterval(currentLoadingInterval);
    currentLoadingInterval = null;
  }
}

// MODIFICATION: 1.1/1.2. Changed signature, settingsModalHandler is no longer needed
// MODIFICATION: 3.1. Changed signature, added themeHandler
export function updateUIForAuthState(user, logoutHandler, deleteAccountHandler, themeHandler) {
  _ensureElements();
  if (user) {
    // BUGFIX: 5.1. Add view toggling logic back
    elements.loginView.classList.add('hidden');
    elements.chatView.classList.remove('hidden');
    if (elements.controlPanelView) elements.controlPanelView.classList.add('hidden');

    // MODIFICATION: 3.2. Re-ordered sidebar template
    const pic = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;
    const name = user.name || user.email || 'User';
    
    elements.sidebarContainer.innerHTML = `
        <div id="sidebar-overlay" class="fixed inset-0 bg-black/50 z-30 hidden md:hidden"></div>
        <aside id="sidebar" class="fixed inset-y-0 left-0 w-80 bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-white flex flex-col z-40 transform -translate-x-full transition-transform duration-300 ease-in-out md:translate-x-0 h-full border-r border-gray-200 dark:border-gray-800">
          <div class="p-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between shrink-0">
            <div class="flex items-center gap-3">
              <div class="app-logo h-10 w-10">
                <img src="assets/logo.png" alt="SAFi Logo" class="rounded-lg w-full h-full" onerror="this.onerror=null; this.src='https://placehold.co/40x40/22c55e/FFFFFF?text=S'">
              </div>
              <div>
                <h1 class="text-lg font-bold">SAFi</h1>
                <p class="text-xs text-gray-500 dark:text-gray-400">The Governance Engine For AI</p>
              </div>
            </div>
            <button id="close-sidebar-button" type="button" aria-label="Close sidebar" class="p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 md:hidden">
              <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>
          
          <!-- MODIFICATION: 3.2. New Chat button at top -->
          <div class="p-4 shrink-0">
            <button id="new-chat-button" type="button" class="w-full bg-green-600 text-white font-semibold px-4 py-2.5 rounded-lg hover:bg-green-700 transition-colors flex items-center justify-center gap-2 shadow-sm hover:shadow-md">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
              New Chat
            </button>
          </div>
           
          <nav id="convo-list" aria-label="Conversation history" class="flex-1 overflow-y-auto p-2 space-y-0.5 custom-scrollbar min-h-0">
            <h3 class="px-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">Conversations</h3>
          </nav>
          
          <!-- MODIFICATION: 3.2. User Profile and Control Panel at bottom -->
          <!-- MODIFICATION: 4.1. Combined Profile and Settings Button -->
          <div id="user-profile-container" class="p-4 border-t border-gray-200 dark:border-gray-800 shrink-0">
            <!-- User Profile & Settings Button -->
            <div class="flex items-center justify-between gap-3 min-w-0">
              
              <!-- Left Side: Avatar + Name -->
              <div class="flex items-center gap-3 min-w-0 flex-1">
                <img src="${pic}" alt="User Avatar" class="w-10 h-10 rounded-full">
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-semibold truncate">${name}</p>
                  <p class="text-xs text-neutral-500 dark:text-neutral-400 truncate">${user.email}</p>
                </div>
              </div>

              <!-- Right Side: Settings Icon Button -->
              <button id="control-panel-btn" type="button" class="shrink-0 p-2 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors" aria-label="Open Control Panel">
                <svg class="w-6 h-6 text-neutral-600 dark:text-neutral-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0 3.35a1.724 1.724 0 001.066 2.573c-.94-1.543.826 3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
              </button>
            </div>
            
            <!-- The original button is now removed -->
          </div>
        </aside>
    `;
    // MODIFICATION: 3.1. Removed all the old user-profile-container logic
    // ... no logic needed, markup is self-contained

  } else {
    elements.sidebarContainer.innerHTML = '';
    elements.loginView.classList.remove('hidden');
    elements.chatView.classList.add('hidden');
    // MODIFICATION: 1.1. Hide Control Panel view on logout
    if (elements.controlPanelView) elements.controlPanelView.classList.add('hidden');
  }
}

function createDropdownMenu(convoId, handlers) {
  const menu = document.createElement('div');
  menu.className = 'convo-menu-dropdown fixed z-50 w-36 bg-white dark:bg-neutral-800 rounded-lg shadow-xl border border-neutral-200 dark:border-neutral-700 p-1';
  menu.dataset.menuId = convoId;
  
  const renameButton = document.createElement('button');
  renameButton.className = "flex items-center gap-3 w-full text-left px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-md";
  renameButton.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.5L15.232 5.232z"></path></svg>
    <span>Rename</span>
  `;
  renameButton.addEventListener('click', (e) => {
    e.stopPropagation();
    closeAllConvoMenus();
    handlers.renameHandler(convoId, document.querySelector(`a[data-id="${convoId}"] .convo-title`).textContent);
  });
  
  const deleteButton = document.createElement('button');
  deleteButton.className = "flex items-center gap-3 w-full text-left px-3 py-2 text-sm text-red-600 dark:text-red-500 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-md";
  deleteButton.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-4v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
    <span>Delete</span>
  `;
  deleteButton.addEventListener('click', (e) => {
    e.stopPropagation();
    closeAllConvoMenus();
    handlers.deleteHandler(convoId);
  });

  menu.appendChild(renameButton);
  menu.appendChild(deleteButton);
  
  menu.addEventListener('click', (e) => e.stopPropagation());

  return menu;
}

function positionDropdown(menu, button) {
  const rect = button.getBoundingClientRect();
  menu.style.top = 'auto';
  menu.style.bottom = `${window.innerHeight - rect.top + 4}px`; // 4px above button
  menu.style.left = 'auto';
  menu.style.right = `${window.innerWidth - rect.right}px`; // Align right edges
}

export function prependConversationLink(convo, handlers) {
  _ensureElements();
  const convoList = document.getElementById('convo-list');
  if (!convoList) return;

  const link = renderConversationLink(convo, handlers);
  const listHeading = convoList.querySelector('h3');
  
  if (listHeading) {
    listHeading.after(link); // Insert after the "Conversations" heading
  } else {
    convoList.prepend(link); // Fallback if no heading
  }
}

export function renderConversationLink(convo, handlers) {
  _ensureElements();
  const { switchHandler, renameHandler, deleteHandler } = handlers;
  const link = document.createElement('a');
  link.href = '#';
  link.dataset.id = convo.id;
  
  link.className = 'group relative flex items-start justify-between px-3 py-2 hover:bg-neutral-200 dark:hover:bg-neutral-800 rounded-lg transition-colors duration-150';
  
  link.innerHTML = `
    <div class="flex-1 min-w-0 pr-8">
        <span class="convo-title truncate block text-sm font-medium">${convo.title || 'Untitled'}</span>
        <span class="convo-timestamp truncate block text-xs text-neutral-500 dark:text-neutral-400">
            ${convo.last_updated ? formatRelativeTime(convo.last_updated) : ''}
        </span>
    </div>
    <button data-action="menu" class="convo-menu-button opacity-0 group-hover:opacity-100 focus:opacity-100 
                   absolute right-2 top-1/2 -translate-y-1/2 
                   p-1.5 rounded-full hover:bg-neutral-300 dark:hover:bg-neutral-700" 
            aria-label="Conversation options">
       <svg class="w-5 h-5 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z"></path></svg>
    </button>
  `;
  
  let longPressTimer = null;
  let isLongPress = false;
  const longPressDuration = 500; // 500ms for a long press

  const handleTouchStart = (e) => {
    isLongPress = false;
    
    longPressTimer = setTimeout(() => {
      isLongPress = true;
      
      const actionButton = link.querySelector('button[data-action="menu"]');
      if (!actionButton) return;

      e.preventDefault(); 
      e.stopPropagation();
      
      if (window.navigator && window.navigator.vibrate) {
        window.navigator.vibrate(50);
      }
      
      if (openDropdown) {
        closeAllConvoMenus();
        return;
      }

      const menu = createDropdownMenu(convo.id, handlers);
      positionDropdown(menu, actionButton);
      document.body.appendChild(menu);
      openDropdown = menu;

    }, longPressDuration);
  };

  const handleTouchEnd = (e) => {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }
    
    if (isLongPress) {
      e.preventDefault();
      e.stopPropagation();
    }
  };

  const handleTouchMove = () => {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }
  };

  link.addEventListener('touchstart', handleTouchStart, { passive: false });
  link.addEventListener('touchend', handleTouchEnd);
  link.addEventListener('touchcancel', handleTouchMove);
  link.addEventListener('touchmove', handleTouchMove);

  link.addEventListener('contextmenu', (e) => {
      e.preventDefault();
  });
  
  link.addEventListener('click', (e) => {
    if (isLongPress) {
        e.preventDefault();
        e.stopPropagation();
        return;
    }

    const actionButton = e.target.closest('button[data-action="menu"]');

    if (actionButton) {
      e.preventDefault();
      e.stopPropagation();
      
      if (openDropdown) {
        closeAllConvoMenus();
        return;
      }

      const menu = createDropdownMenu(convo.id, handlers);
      positionDropdown(menu, actionButton);
      document.body.appendChild(menu);
      openDropdown = menu;
      
    } else {
      e.preventDefault();
      closeAllConvoMenus();
      if (window.innerWidth < 768) closeSidebar();
      switchHandler(convo.id);
    }
  });
  return link;
}

export function displaySimpleGreeting(firstName) {
  _ensureElements();
  const existingGreeting = elements.chatWindow.querySelector('.simple-greeting');
  if (existingGreeting) existingGreeting.remove();

  const greetingDiv = document.createElement('div');
  greetingDiv.className = 'simple-greeting text-4xl font-bold text-center py-8 text-neutral-800 dark:text-neutral-200';
  greetingDiv.textContent = `Hi ${firstName}`;
  elements.chatWindow.appendChild(greetingDiv);
}

export function displayMessage(sender, text, date = new Date(), messageId = null, payload = null, whyHandler = null, options = {}) {
  _ensureElements();
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
    // MODIFICATION: Add profile name if available
    const profileName = (payload && payload.profile) ? payload.profile : null;
    
    // *** THIS IS THE NEW CREATIVE THEME ***
    // This is the new tag without background, which will get a tail from styles.css
const toTitleCase = str => 
  str.replace(/\w\S*/g, w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());

/*
// MODIFICATION: Removed the profile name HTML from the chat bubble
const profileNameHtml = profileName 
  ? `<div class="ai-name ai-profile-name-tag relative inline-flex items-center gap-1.5 text-green-700 dark:text-green-500 text-xl font-bold mb-2">
      <!-- REMOVED SHIELD ICON -->
      <span class="font-bold">${toTitleCase(profileName)}</span>
     </div>` 
  : '';
*/
const profileNameHtml = ''; // <-- This removes the name from the bubble

    // *** NEW: Call the Avatar Map ***
    const avatarUrl = getAvatarForProfile(profileName);

    messageDiv.innerHTML = `
      <!-- NEW: AI Avatar Column -->
      <div class="ai-avatar">
        <img src="${avatarUrl}" alt="${profileName || 'SAFi'} Avatar" class="w-full h-full rounded-lg">
      </div>
      <!-- END NEW -->
      <div class="ai-content-wrapper">
        ${profileNameHtml} <!-- MODIFICATION: Added Profile Name -->
        <div class="chat-bubble">
          <!-- Content will be injected here -->
          <div class="meta"></div>
        </div>
      </div>
    `;
    const bubble = messageDiv.querySelector('.chat-bubble');
    bubble.insertAdjacentHTML('afterbegin', DOMPurify.sanitize(marked.parse(String(text ?? ''))));
  } else {
    const bubbleHtml = DOMPurify.sanitize(marked.parse(String(text ?? '')));
    const avatarUrl = options.avatarUrl || `https://placehold.co/40x40/7e22ce/FFFFFF?text=U`;
    messageDiv.innerHTML = `
        <div class="user-content-wrapper">
           <div class="chat-bubble">
             ${bubbleHtml}
             <div class="meta"></div>
           </div>
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
      // rightMeta.appendChild(makeCopyButton(text)); // <-- REMOVE THIS LINE
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
    _ensureElements();
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

// *** (Task 2) Rewrite this function ***
// MODIFICATION: Accept profileName
export function showLoadingIndicator(profileName) {
  _ensureElements();
  clearLoadingInterval(); // Clear any previous timer

  const emptyState = elements.chatWindow.querySelector('.empty-state-container');
  if (emptyState) emptyState.remove();
  const simpleGreeting = elements.chatWindow.querySelector('.simple-greeting');
  if (simpleGreeting) simpleGreeting.remove();
  
  maybeInsertDayDivider(new Date());

  const loadingContainer = document.createElement('div');
  loadingContainer.className = 'message-container';
  
  // *** NEW: Call Avatar Map for default avatar ***
  // MODIFICATION: Use profileName if available, otherwise fallback to null
  const avatarUrl = getAvatarForProfile(profileName || null); 
  const altText = (profileName || 'SAFi') + ' Avatar';

  loadingContainer.innerHTML = `
    <div class="message ai">
        <!-- NEW: AI Avatar Column -->
        <div class="ai-avatar">
            <img src="${avatarUrl}" alt="${altText}" class="w-full h-full rounded-lg">
        </div>
        <!-- END NEW -->
        <div class="ai-content-wrapper">
            <div class="flex items-center gap-3">
              <div class="thinking-spinner"></div>
              <span id="thinking-status" class="text-gray-500 dark:text-gray-400 italic">Thinking...</span>
            </div>
        </div>
    </div>`;
  elements.chatWindow.appendChild(loadingContainer);
  scrollToBottom();

  const statusSpan = loadingContainer.querySelector('#thinking-status');

  // *** DEFINE NEW 3-STAGE MESSAGE POOLS ***
  
  // Stage 1: Intellect (Fires immediately)
  const stage1IntellectMessages = [
    "Consulting with the Intellect...",
    "Packaging the prompt for the AI model...",
    "Drafting response..."
  ];
  
  // Stage 2: Will (Fires after 3-4 seconds)
  const stage2WillMessages = [
    "Intellect draft received. Consulting Will faculty...",
    "Analyzing draft against non-negotiable rules...",
    "Running gatekeeper check..."
  ];

  // Stage 3: Delayed (Fires after 6-8+ seconds)
  // This new pool acknowledges the delay is due to a complex
  // prompt for the LLM (Gemini, Claude, GPT).
  const stage3DelayedMessages = [
    "This is a complex prompt, so generation is taking longer than usual...",
    "If you are using claude,Gemini or GTP for the Intellect, those models take longer, sorry..",
    "Ensuring a high-quality draft, please wait...",
    "Almost done hang on...",
    "Just a few more moments..."
  ];
  // *** END OF NEW MESSAGE POOLS ***

  let stage = 0;

  const updateStatus = () => {
    stage++;
    let messagePool;

    if (stage === 1) {
      // Stage 1: Intellect
      messagePool = stage1IntellectMessages;
    } else if (stage === 2) {
      // Stage 2: Will
      messagePool = stage2WillMessages;
    } else {
      // Stage 3: Delayed (and all subsequent ticks)
      // The simulation now loops indefinitely in the "Delayed" stage
      // until it is stopped by main.js.
      messagePool = stage3DelayedMessages;
    }
    
    // Pick a random message from the current stage's pool
    const message = messagePool[Math.floor(Math.random() * messagePool.length)];
    if (statusSpan) {
      statusSpan.textContent = message;
    }
  };

  // Show the first message (from Stage 1) immediately
  updateStatus();

  // Set an interval with a randomized delay to feel more "real"
  // A slightly longer, more varied delay feels more natural
  const randomDelay = 3000 + (Math.random() * 1500); // 3-4.5 seconds
  currentLoadingInterval = setInterval(updateStatus, randomDelay);

  return loadingContainer;
}


export function showToast(message, type = 'info', duration = 3000) {
  _ensureElements();
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
    _ensureElements();
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
  _ensureElements();
  if (kind === 'conscience') {
    const payload = data || { ledger: [], profile: null, values: [], spirit_score: null, spirit_scores_history: [] };
    setupModal(payload);
    elements.conscienceModal.classList.remove('hidden');
  } else if (kind === 'delete') {
    elements.deleteAccountModal.classList.remove('hidden');
  } 
  // MODIFICATION: 1.1. Removed 'settings' modal kind
  // MODIFICATION: 1.2. Removed 'app-settings' modal kind (now in CP)
  else if (kind === 'rename') {
    // data = { oldTitle }
    if (elements.renameInput) {
        elements.renameInput.value = data.oldTitle;
    }
    elements.renameModal.classList.remove('hidden');
    if (elements.renameInput) {
        elements.renameInput.focus();
        elements.renameInput.select();
    }
  } else if (kind === 'delete-convo') {
    elements.deleteConvoModal.classList.remove('hidden');
  }
  
  elements.modalBackdrop.classList.remove('hidden');
}

export function closeModal() {
  _ensureElements();
  elements.modalBackdrop.classList.add('hidden');
  elements.conscienceModal.classList.add('hidden');
  elements.deleteAccountModal.classList.add('hidden');
  // MODIFICATION: 1.1. Removed settingsModal
  // MODIFICATION: 1.2. Removed appSettingsModal
  elements.renameModal.classList.add('hidden');
  elements.deleteConvoModal.classList.add('hidden');

  // MODIFICATION: 1.1. Removed old modal reset logic
}

function renderIntro(payload) {
    const profileName = payload.profile ? `the <strong>${payload.profile}</strong>` : 'the current';
    return `<p class="text-base text-neutral-600 dark:text-neutral-300 mb-6">This response was shaped by ${profileName} ethical profile. Here’s a breakdown of the reasoning:</p>`;
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
    
    // MODIFICATION: 1.4. Visual Confidence Bars
    // FIX: Changed responsive classes for consistency
    const confidenceDisplayHtml = item.confidence ? `
        <div class="flex items-center gap-2 w-full sm:w-auto sm:min-w-[160px]">
            <span class="text-xs font-medium text-neutral-500 dark:text-neutral-400 hidden sm:inline">Confidence</span>
            <div class="h-1.5 flex-1 rounded-full bg-neutral-200 dark:bg-neutral-700">
                <div class="h-full rounded-full bg-green-500" style="width: ${item.confidence * 100}%"></div>
            </div>
            <span class="text-xs font-semibold text-neutral-600 dark:text-neutral-300 w-9 text-right">${Math.round(item.confidence * 100)}%</span>
        </div>
    ` : '';
    // END MODIFICATION

    return `
        <div class="bg-white dark:bg-neutral-800/60 p-4 rounded-lg border border-neutral-200 dark:border-neutral-700/80">
            <div class="flex items-start sm:items-center justify-between gap-4 mb-2 flex-col sm:flex-row">
                <div class="font-semibold text-neutral-800 dark:text-neutral-200">${item.value}</div>
                ${confidenceDisplayHtml}
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
  _ensureElements();
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
}

function maybeInsertDayDivider(date) {
  _ensureElements();
  const key = date.toLocaleDateString();
  if (key !== lastRenderedDay) {
    lastRenderedDay = key;
    const div = document.createElement('div');
    div.className = 'flex items-center justify-center my-2';
    div.innerHTML = `<div class="text-xs text-neutral-500 dark:text-neutral-400 px-3 py-1 rounded-full bg-neutral-100 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700">${date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}</div>`;
    elements.chatWindow.appendChild(div);
  }
}

/* REMOVE THIS ENTIRE FUNCTION
function makeCopyButton(text) {
  const btn = document.createElement('button');
  btn.className = 'meta-btn p-1 hover:bg-neutral-200 dark:hover:bg-neutral-700 rounded-md';
  btn.title = 'Copy Text';
  
  const icon = `<svg class="w-4 h-4 text-neutral-500 dark:text-neutral-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>`;
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
*/

export function displayEmptyState(activeProfile, promptClickHandler) {
  _ensureElements();
  const existingEmptyState = document.querySelector('.empty-state-container');
  if (existingEmptyState) {
    existingEmptyState.remove();
  }

  if (activeProfile && elements.chatWindow) {
    const valuesHtml = (activeProfile.values || []).map(v => `<span class="value-chip">${v.value}</span>`).join(' ');
    const promptsHtml = (activeProfile.example_prompts || []).map(p => `<button class="example-prompt-btn">"${p}"</button>`).join('');
    const descriptionHtml = activeProfile.description 
      ? `<p class="text-base text-neutral-600 dark:text-neutral-300 mt-4 max-w-2xl mx-auto">${activeProfile.description}</p>` // MODIFIED: max-w-md to max-w-2xl
      : '';
    
    // *** NEW: Call Avatar Map ***
    const avatarUrl = getAvatarForProfile(activeProfile.name);

    const emptyStateContainer = document.createElement('div');
    emptyStateContainer.className = 'empty-state-container';
    // MODIFICATION: 1.1. Updated help text for Control Panel
    // MODIFICATION: Added Avatar
    emptyStateContainer.innerHTML = `<div class="text-center pt-8">
        <!-- MODIFICATION: Moved avatar to appear AFTER the name -->
        <p class="text-lg text-neutral-500 dark:text-neutral-400">SAFi is currently set with the</p>
        <h2 class="text-2xl font-semibold my-2">${activeProfile.name || 'Default'}</h2>
        <!-- NEW: Profile Avatar -->
        <img src="${avatarUrl}" alt="${activeProfile.name || 'SAFi'} Avatar" class="w-20 h-20 rounded-lg mx-auto mt-4"> <!-- Changed margin to mt-4 -->
        <!-- END NEW -->
        <p class="text-sm text-neutral-500 dark:text-neutral-400">persona, which includes these values:</p>
        <div class="flex flex-wrap justify-center gap-2 my-4 max-w-2xl mx-auto">${valuesHtml}</div> <!-- MODIFIED: max-w-md to max-w-2xl -->
        ${descriptionHtml}
         <div class="mt-6 text-sm text-neutral-700 dark:text-neutral-300">
            To choose a different persona, open the <svg class="inline-block w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0 3.35a1.724 1.724 0 001.066 2.573c-.94-1.543.826 3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg> 'Control Panel'.
        </div>
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-6 mb-3">To begin, type below or pick an example prompt:</p>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 max-w-6xl mx-auto">${promptsHtml}</div> <!-- MODIFIED: max-w-4xl to max-w-6xl -->
      </div>`;
    
    elements.chatWindow.appendChild(emptyStateContainer);

    emptyStateContainer.querySelectorAll('.example-prompt-btn').forEach(btn => {
        btn.addEventListener('click', () => promptClickHandler(btn.textContent.replace(/"/g, '')));
    });
  }
}

export function resetChatView() {
  _ensureElements();
  lastRenderedDay = '';
  while (elements.chatWindow.firstChild) {
    elements.chatWindow.removeChild(elements.chatWindow.firstChild);
  }
}

export function setActiveConvoLink(id) {
  _ensureElements();
  document.querySelectorAll('#convo-list > a').forEach(link => {
    const isActive = link.dataset.id === String(id);
    const title = link.querySelector('.convo-title');
    const timestamp = link.querySelector('.convo-timestamp');

    link.classList.toggle('bg-green-600', isActive);
    link.classList.toggle('text-white', isActive);
    link.classList.toggle('dark:bg-green-600', isActive);
    link.classList.toggle('dark:text-white', isActive);
    link.classList.toggle('text-neutral-900', !isActive);
    link.classList.toggle('dark:text-white', !isActive);
    link.classList.toggle('hover:bg-neutral-200', !isActive);
    link.classList.toggle('dark:hover:bg-neutral-800', !isActive);
    
    title?.classList.toggle('font-semibold', isActive);
    title?.classList.toggle('font-medium', !isActive);

    if (timestamp) {
      timestamp.classList.toggle('text-green-100', isActive);
      timestamp.classList.toggle('dark:text-green-100', isActive);
      
      timestamp.classList.toggle('text-neutral-500', !isActive);
      timestamp.classList.toggle('dark:text-neutral-400', !isActive);
    }
  });
}

// *** THIS IS THE NEW/FIXED FUNCTION ***
// It updates both mobile and desktop titles.
export function updateChatTitle(title) {
  const mobileTitle = document.getElementById('chat-title');
  const desktopTitle = document.getElementById('chat-title-desktop'); // New ID
  const newTitle = title || 'SAFi';

  if (mobileTitle) {
    mobileTitle.textContent = newTitle;
  }
  if (desktopTitle) {
    desktopTitle.textContent = newTitle;
  }
}
// *** END OF NEW FUNCTION ***

// MODIFICATION: Updated function to include avatar thumbnails
export function updateActiveProfileChip(profileName) {
  _ensureElements();
  
  const avatarUrl = getAvatarForProfile(profileName);
  // MODIFICATION: Split text label and profile name
  const textLabel = "Profile:";
  const profileNameText = profileName || 'Default';

  if (elements.activeProfileChip) {
    // This is the chip by the composer
    elements.activeProfileChip.classList.add('flex', 'items-center', 'gap-2'); // Ensure flex layout
    // MODIFICATION: Re-ordered to Text -> Image -> Name
    elements.activeProfileChip.innerHTML = `
      <span class="truncate flex-shrink-0">${textLabel}</span>
      <img src="${avatarUrl}" alt="${profileName || 'SAFi'} Avatar" class="w-5 h-5 rounded-md flex-shrink-0">
      <span class="truncate">${profileNameText}</span>
    `;
  }
  if (elements.activeProfileChipMobile) {
    // This is the chip in the top bar
    // MODIFICATION: Added mx-auto to center the chip
    elements.activeProfileChipMobile.classList.add('flex', 'items-center', 'gap-2', 'mx-auto'); // Ensure flex layout
    // MODIFICATION: Re-ordered to Text -> Image -> Name
    elements.activeProfileChipMobile.innerHTML = `
      <span class="font-semibold truncate flex-shrink-0">${textLabel}</span>
      <img src="${avatarUrl}" alt="${profileName || 'SAFi'} Avatar" class="w-6 h-6 rounded-lg flex-shrink-0">
      <span class="font-semibold truncate">${profileNameText}</span>
    `;
  }
}


// MODIFICATION: 1.1. Repurposed for Control Panel
// MODIFICATION: 3.1. Added App Settings tab
export function setupControlPanelTabs() {
    _ensureElements();
    const tabs = [elements.cpNavProfile, elements.cpNavModels, elements.cpNavDashboard, elements.cpNavAppSettings];
    const panels = [elements.cpTabProfile, elements.cpTabModels, elements.cpTabDashboard, elements.cpTabAppSettings];
    
    tabs.forEach((tab, index) => {
        if (!tab) return;
        tab.addEventListener('click', () => {
            tabs.forEach(t => t?.classList.remove('active'));
            tab.classList.add('active');
            
            panels.forEach(p => p?.classList.add('hidden'));
            if (panels[index]) {
                panels[index].classList.remove('hidden');
            }

            // Special handling for dashboard iframe
            if (tab === elements.cpNavDashboard) {
                renderSettingsDashboardTab(); // Lazy-load iframe
            }
        });
    });
    
    if (tabs[0]) {
      tabs[0].click();
    }
}

// Renders the "Ethical Profile" tab
// MODIFICATION: 1.1. Renders into Control Panel
// MODIFICATION: Added Profile Avatar
export function renderSettingsProfileTab(profiles, activeProfileKey, onProfileChange) {
  _ensureElements();
    const container = elements.cpTabProfile;
    if (!container) return;
    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Choose Ethical Profile</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-6 text-sm">Select a profile to define the AI's values, worldview, and rules. The chat will reload to apply the change.</p>
        <div class="space-y-4" role="radiogroup">
            ${profiles.map(profile => {
                // *** NEW: Call Avatar Map ***
                const avatarUrl = getAvatarForProfile(profile.name);
                return `
                <label class="block p-4 border ${profile.key === activeProfileKey ? 'border-green-600 bg-green-50 dark:bg-green-900/30' : 'border-neutral-300 dark:border-neutral-700'} rounded-lg cursor-pointer hover:border-green-500 dark:hover:border-green-400 transition-colors">
                    <div class="flex items-center justify-between">
                        <!-- NEW: Avatar + Name Flexbox -->
                        <div class="flex items-center gap-3">
                            <img src="${avatarUrl}" alt="${profile.name} Avatar" class="w-8 h-8 rounded-lg">
                            <span class="font-semibold text-base text-neutral-800 dark:text-neutral-200">${profile.name}</span>
                        </div>
                        <!-- END NEW -->
                        <input type="radio" name="ethical-profile" value="${profile.key}" class="form-radio text-green-600 focus:ring-green-500" ${profile.key === activeProfileKey ? 'checked' : ''}>
                    </div>
                    <p class="text-sm text-neutral-600 dark:text-neutral-300 mt-2">${profile.description || ''}</p>
                </label>
            `}).join('')}
        </div>
    `;

    container.querySelectorAll('input[name="ethical-profile"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            onProfileChange(e.target.value);
            container.querySelectorAll('label').forEach(label => {
                label.classList.remove('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
                label.classList.add('border-neutral-300', 'dark:border-neutral-700');
            });
            radio.closest('label').classList.add('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
            radio.closest('label').classList.remove('border-neutral-300', 'dark:border-neutral-700');
        });
    });
}


// Renders the "AI Models" tab
// MODIFICATION: 1.1. Renders into Control Panel
export function renderSettingsModelsTab(availableModels, user, onModelsSave) {
    _ensureElements();
    const container = elements.cpTabModels;
    if (!container) return;
    
    const createSelect = (id, label, selectedValue) => `
        <div>
            <label for="${id}" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">${label}</label>
            <select id="${id}" class="settings-modal-select">
                ${availableModels.map(model => `
                    <option value="${model}" ${model === selectedValue ? 'selected' : ''}>${model}</option>
                `).join('')}
            </select>
        </div>
    `;

    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Choose AI Models</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-6 text-sm">Assign a specific AI model to each of the three faculties. Changes will apply on the next page load.</p>
        <div class="space-y-4">
            ${createSelect('model-select-intellect', 'Intellect (Generation)', user.intellect_model)}
            ${createSelect('model-select-will', 'Will (Gatekeeping)', user.will_model)}
            ${createSelect('model-select-conscience', 'Conscience (Auditing)', user.conscience_model)}
        </div>
        <div class="mt-6 text-right">
            <button id="save-models-btn" class="px-5 py-2.5 rounded-lg font-semibold bg-green-600 text-white hover:bg-green-700 text-sm transition-colors">
                Save Changes
            </button>
        </div>
    `;

    document.getElementById('save-models-btn').addEventListener('click', () => {
        const newModels = {
            intellect_model: document.getElementById('model-select-intellect').value,
            will_model: document.getElementById('model-select-will').value,
            conscience_model: document.getElementById('model-select-conscience').value,
        };
        onModelsSave(newModels);
    });
}

// Renders the Dashboard tab content
// MODIFICATION: 1.1. Renders into Control Panel, lazy-loads iframe
// MODIFICATION: Refactored to add padding to header and make iframe fill space
export function renderSettingsDashboardTab() {
    _ensureElements();
    const container = elements.cpTabDashboard; // This container is 'flex-1 flex flex-col' from index.html
    if (!container) return;

    // Only add iframe if it's not already there
    if (container.querySelector('iframe')) return;

    // This function clears the container
    container.innerHTML = ''; 

    // 1. Create Header Div with padding
    const headerDiv = document.createElement('div');
    headerDiv.className = "p-6 shrink-0"; // Add padding here. 'shrink-0' is important.
    headerDiv.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Trace & Analyze</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-0 text-sm">Analyze ethical alignment and trace decisions across all conversations.</p>
    `;
    
    // 2. Create Iframe Container Div
    const iframeContainer = document.createElement('div');
    // 'flex-1' makes it take remaining space. Added padding for the frame.
        iframeContainer.className = "w-full h-[1024px] overflow-hidden";

    
    const iframe = document.createElement('iframe');
    iframe.src = "https://dashboard.selfalignmentframework.com/?embed=true";
    // Make iframe fill the container.
    iframe.className = "w-full h-full rounded-lg"; 
    iframe.title = "SAFi Dashboard";
    iframe.sandbox = "allow-scripts allow-same-origin allow-forms";
    
    iframeContainer.appendChild(iframe);

    // 3. Append both to the main container
    container.appendChild(headerDiv);
    container.appendChild(iframeContainer);
}

// MODIFICATION: 1.2. New function for App Settings modal
// MODIFICATION: 3.1. Re-purposed for App Settings *Tab*
export function renderSettingsAppTab(currentTheme, onThemeChange, onLogout, onDelete) {
    _ensureElements();
    const container = elements.cpTabAppSettings;
    if (!container) return;

    const themes = [
        { key: 'light', name: 'Light' },
        { key: 'dark', name: 'Dark' },
        { key: 'system', name: 'System Default' }
    ];

    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">App Settings</h3>
        
        <div class_="space-y-4">
            <h4 class="text-base font-semibold text-neutral-700 dark:text-neutral-300 mb-2">Theme</h4>
            <div class="space-y-2" role="radiogroup">
                ${themes.map(theme => `
                    <label class="flex items-center gap-3 p-3 border ${theme.key === currentTheme ? 'border-green-600 bg-green-50 dark:bg-green-900/30' : 'border-neutral-300 dark:border-neutral-700'} rounded-lg cursor-pointer hover:border-green-500 dark:hover:border-green-400 transition-colors">
                        <input type="radio" name="theme-select" value="${theme.key}" class="form-radio text-green-600 focus:ring-green-500" ${theme.key === currentTheme ? 'checked' : ''}>
                        <span class="text-sm font-medium text-neutral-800 dark:text-neutral-200">${theme.name}</span>
                    </label>
                `).join('')}
            </div>
            
            <h4 class="text-base font-semibold text-neutral-700 dark:text-neutral-300 mt-8 mb-2">Account</h4>
            <div class="space-y-3">
                <button id="cp-logout-btn" class="w-full text-left px-4 py-3 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-800 rounded-lg border border-neutral-300 dark:border-neutral-700 transition-colors">
                    Sign Out
                </button>
                <button id="cp-delete-account-btn" class="w-full text-left px-4 py-3 text-sm font-medium text-red-600 dark:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg border border-red-300 dark:border-red-700 transition-colors">
                    Delete Account...
                </button>
            </div>
        </div>
    `;

    // Add event listeners
    container.querySelectorAll('input[name="theme-select"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const newTheme = e.target.value;
            onThemeChange(newTheme); // This will call applyTheme in main.js
            
            // Manually update UI for radio buttons
            container.querySelectorAll('label').forEach(label => {
                label.classList.remove('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
                label.classList.add('border-neutral-300', 'dark:border-neutral-700');
            });
            radio.closest('label').classList.add('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
            radio.closest('label').classList.remove('border-neutral-300', 'dark:border-neutral-700');
        });
    });

    document.getElementById('cp-logout-btn').addEventListener('click', onLogout);
    document.getElementById('cp-delete-account-btn').addEventListener('click', onDelete);
}