// ui-auth-sidebar.js

import { formatRelativeTime } from './utils.js';
import * as ui from './ui.js'; 

// --- ICON TEMPLATES (Need to be imported or defined here for link rendering) ---
const iconMenuDots = `<svg class="w-5 h-5 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z"></path></svg>`;
// --- NEW: Pin Icon ---
const iconPin = `<svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 1a1 1 0 011 1v4.586l2.707 2.707a1 1 0 01-1.414 1.414L11 9.414V16a1 1 0 11-2 0V9.414l-1.293 1.293a1 1 0 01-1.414-1.414L9 5.586V2a1 1 0 011-1z" clip-rule="evenodd"></path><path d="M8 16a2 2 0 104 0h-4z"></path></svg>`;
// --- END NEW ---


// --- AVATAR HELPERS ---
/**
 * Maps a profile name to a static avatar image path.
 * @param {string | null} profileName 
 * @returns {string} The path to the avatar image
 */
export function getAvatarForProfile(profileName) {
  // Normalize the profile name to lowercase, trimmed, and replace underscores with spaces for common matching
  let cleanName = profileName ? profileName.trim().toLowerCase() : null;

  // Check for common internal key format (e.g., 'health_navigator')
  if (cleanName && cleanName.includes('_')) {
    // If it's the internal key, use the key itself for matching
    // and also try the space-separated version for robustness
    if (cleanName === 'health_navigator') {
        return 'assets/health_navigator.svg';
    }
    // Fall through to switch after primary check
  }

  switch (cleanName) {
    case 'the philosopher':
      return 'assets/philosopher.svg';
    case 'the fiduciary':
      return 'assets/fiduciary.svg';
    case 'the health navigator':
    case 'health navigator': // Added for robustness
      return 'assets/health_navigator.svg'; // <-- FIX: Corrected path
    case 'the jurist':
      return 'assets/jurist.svg';
    case 'the bible scholar':
      return 'assets/bible_scholar.svg';
    case 'the safi guide':
    default:
      return 'assets/safi.svg';
  }
}

// --- GLOBAL UI RENDERING (Auth & Sidebar) ---
export function updateUIForAuthState(user) {
  ui._ensureElements();
  if (user) {
    ui.elements.loginView.classList.add('hidden');
    ui.elements.chatView.classList.remove('hidden');
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');

    const pic = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;
    const name = user.name || user.email || 'User';
    
    // NOTE: Logout/Delete handlers are often attached outside the render, 
    // but the original code included the full static HTML here.
    // For simplicity, we keep the original rendering method.

    ui.elements.sidebarContainer.innerHTML = `
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
          
          <div class="p-4 shrink-0">
            <button id="new-chat-button" type="button" class="w-full bg-green-600 text-white font-semibold px-4 py-2.5 rounded-lg hover:bg-green-700 transition-colors flex items-center justify-center gap-2 shadow-sm hover:shadow-md">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
              New Chat
            </button>
          </div>
           
          <nav id="convo-list" aria-label="Conversation history" class="flex-1 overflow-y-auto p-2 space-y-0.5 custom-scrollbar min-h-0">
            <h3 class="px-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">Conversations</h3>
          </nav>
          
          <div id="user-profile-container" class="p-4 border-t border-gray-200 dark:border-gray-800 shrink-0">
            <div class="flex items-center justify-between gap-3 min-w-0">
              
              <div class="flex items-center gap-3 min-w-0 flex-1">
                <img src="${pic}" alt="User Avatar" class="w-10 h-10 rounded-full">
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-semibold truncate">${name}</p>
                  <p class="text-xs text-neutral-500 dark:text-neutral-400 truncate">${user.email}</p>
                </div>
              </div>

              <button id="control-panel-btn" type="button" class="shrink-0 p-2 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors" aria-label="Open Control Panel">
                <svg class="w-6 h-6 text-neutral-600 dark:text-neutral-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924-1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0 3.35a1.724 1.724 0 001.066 2.573c-.94-1.543.826 3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
              </button>
            </div>
          </div>
        </aside>
    `;
  } else {
    ui.elements.sidebarContainer.innerHTML = '';
    ui.elements.loginView.classList.remove('hidden');
    ui.elements.chatView.classList.add('hidden');
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
  }
}

// --- CONVERSATION LINK RENDERING ---

/**
 * Creates the dropdown menu for conversation actions (Rename/Delete).
 * @param {object} convo - The full conversation object.
 * @param {object} handlers - Rename, Delete, and Pin handler functions.
 * @returns {HTMLDivElement} The dropdown menu element.
 */
function createDropdownMenu(convo, handlers) {
  // --- NEW: Destructure all handlers ---
  const { renameHandler, deleteHandler, pinHandler } = handlers;
  
  const menu = document.createElement('div');
  menu.className = 'convo-menu-dropdown fixed z-50 w-36 bg-white dark:bg-neutral-800 rounded-lg shadow-xl border border-neutral-200 dark:border-neutral-700 p-1';
  menu.dataset.menuId = convo.id;
  
  // --- NEW: Pin/Unpin Button ---
  const pinButton = document.createElement('button');
  pinButton.className = "flex items-center gap-3 w-full text-left px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-md";
  pinButton.innerHTML = `
    <span class="w-4 h-4">${iconPin}</span>
    <span>${convo.is_pinned ? 'Unpin' : 'Pin'}</span>
  `;
  pinButton.addEventListener('click', (e) => {
    e.stopPropagation();
    ui.closeAllConvoMenus();
    // Pass the convo id and its current pinned state
    pinHandler(convo.id, convo.is_pinned);
  });
  // --- END NEW ---

  const renameButton = document.createElement('button');
  renameButton.className = "flex items-center gap-3 w-full text-left px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-md";
  renameButton.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.5L15.232 5.232z"></path></svg>
    <span>Rename</span>
  `;
  renameButton.addEventListener('click', (e) => {
    e.stopPropagation();
    ui.closeAllConvoMenus();
    renameHandler(convo.id, document.querySelector(`a[data-id="${convo.id}"] .convo-title`).textContent);
  });
  
  const deleteButton = document.createElement('button');
  deleteButton.className = "flex items-center gap-3 w-full text-left px-3 py-2 text-sm text-red-600 dark:text-red-500 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-md";
  deleteButton.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-4v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
    <span>Delete</span>
  `;
  deleteButton.addEventListener('click', (e) => {
    e.stopPropagation();
    ui.closeAllConvoMenus();
    deleteHandler(convo.id);
  });

  menu.appendChild(pinButton); // Add pin button first
  menu.appendChild(renameButton);
  menu.appendChild(deleteButton);
  menu.addEventListener('click', (e) => e.stopPropagation());

  return menu;
}

/**
 * Positions the dropdown menu relative to the conversation button.
 * @param {HTMLDivElement} menu - The dropdown element.
 * @param {HTMLButtonElement} button - The button element that opened the menu.
 */
function positionDropdown(menu, button) {
  const rect = button.getBoundingClientRect();
  menu.style.top = 'auto';
  menu.style.bottom = `${window.innerHeight - rect.top + 4}px`;
  menu.style.left = 'auto';
  menu.style.right = `${window.innerWidth - rect.right}px`; 
}

/**
 * Prepends a new conversation link to the conversation history list.
 */
export function prependConversationLink(convo, handlers) {
  ui._ensureElements();
  const convoList = document.getElementById('convo-list');
  if (!convoList) return;

  const link = renderConversationLink(convo, handlers);
  const listHeading = convoList.querySelector('h3');
  
  if (listHeading) {
    listHeading.after(link); 
  } else {
    convoList.prepend(link); 
  }
}

/**
 * Renders a single conversation link element.
 */
export function renderConversationLink(convo, handlers) {
  ui._ensureElements();
  const { switchHandler } = handlers;
  const link = document.createElement('a');
  link.href = '#';
  link.dataset.id = convo.id;
  
  link.className = 'group relative flex items-start justify-between px-3 py-2 hover:bg-neutral-200 dark:hover:bg-neutral-800 rounded-lg transition-colors duration-150';
  
  // --- NEW: Add pin icon if convo.is_pinned is true ---
  const pinIconHtml = convo.is_pinned 
    ? `<span class="pin-icon shrink-0 text-neutral-500 dark:text-neutral-400">${iconPin}</span>` 
    : '';

  link.innerHTML = `
    <div class="flex-1 min-w-0 pr-8 flex items-center gap-2">
        ${pinIconHtml}
        <div class="flex-1 min-w-0">
            <span class="convo-title truncate block text-sm font-medium">${convo.title || 'Untitled'}</span>
            <span class="convo-timestamp truncate block text-xs text-neutral-500 dark:text-neutral-400">
                ${convo.last_updated ? formatRelativeTime(convo.last_updated) : ''}
            </span>
        </div>
    </div>
    <button data-action="menu" class="convo-menu-button opacity-0 group-hover:opacity-100 focus:opacity-100 
                   absolute right-2 top-1/2 -translate-y-1/2 
                   p-1.5 rounded-full hover:bg-neutral-300 dark:hover:bg-neutral-700" 
            aria-label="Conversation options">
       ${iconMenuDots}
    </button>
  `;
  // --- END NEW ---
  
  let longPressTimer = null;
  let isLongPress = false;
  const longPressDuration = 500; 

  // --- Long press and touch handling logic for mobile context menu ---

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
      if (document.querySelector('.convo-menu-dropdown')) {
        ui.closeAllConvoMenus();
        return;
      }
      // --- NEW: Pass the full convo object ---
      const menu = createDropdownMenu(convo, handlers);
      positionDropdown(menu, actionButton);
      ui.setOpenDropdown(menu);
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
  
  // --- Click handling ---
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
      
      if (document.querySelector('.convo-menu-dropdown')) {
        ui.closeAllConvoMenus();
        return;
      }
      
      // --- NEW: Pass the full convo object ---
      const menu = createDropdownMenu(convo, handlers);
      positionDropdown(menu, actionButton);
      ui.setOpenDropdown(menu);
      
    } else {
      e.preventDefault();
      ui.closeAllConvoMenus();
      if (window.innerWidth < 768) ui.closeSidebar();
      switchHandler(convo.id);
    }
  });
  return link;
}

/**
 * Highlights the currently active conversation link.
 */
export function setActiveConvoLink(id) {
  ui._ensureElements();
  document.querySelectorAll('#convo-list > a').forEach(link => {
    const isActive = link.dataset.id === String(id);
    const title = link.querySelector('.convo-title');
    const timestamp = link.querySelector('.convo-timestamp');
    // --- NEW: Select the pin icon ---
    const pinIcon = link.querySelector('.pin-icon');

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
    
    // --- NEW: Update pin icon color ---
    if (pinIcon) {
      pinIcon.classList.toggle('text-green-100', isActive);
      pinIcon.classList.toggle('dark:text-green-100', isActive);
      
      pinIcon.classList.toggle('text-neutral-500', !isActive);
      pinIcon.classList.toggle('dark:text-neutral-400', !isActive);
    }
    // --- END NEW ---
  });
}

/**
 * Updates the chat window title (mobile and desktop).
 */
export function updateChatTitle(title) {
  const mobileTitle = document.getElementById('chat-title');
  const desktopTitle = document.getElementById('chat-title-desktop');
  const newTitle = title || 'SAFi';

  if (mobileTitle) {
    mobileTitle.textContent = newTitle;
  }
  if (desktopTitle) {
    desktopTitle.textContent = newTitle;
  }
}

/**
 * Updates the chip displaying the currently active profile/persona.
 */
export function updateActiveProfileChip(profileName) {
  ui._ensureElements();
  
  const avatarUrl = getAvatarForProfile(profileName);
  const textLabel = "Persona:";
  const profileNameText = profileName || 'Default';

  if (ui.elements.activeProfileChip) {
    ui.elements.activeProfileChip.classList.add('flex', 'items-center', 'gap-2');
    ui.elements.activeProfileChip.innerHTML = `
      <span class="truncate flex-shrink-0">${textLabel}</span>
      <img src="${avatarUrl}" alt="${profileName || 'SAFi'} Avatar" class="w-5 h-5 rounded-md flex-shrink-0">
      <span class="truncate">${profileNameText}</span>
    `;
  }
  if (ui.elements.activeProfileChipMobile) {
    ui.elements.activeProfileChipMobile.classList.add('flex', 'items-center', 'gap-2', 'mx-auto');
    ui.elements.activeProfileChipMobile.innerHTML = `
      <span class="font-semibold truncate flex-shrink-0">${textLabel}</span>
      <img src="${avatarUrl}" alt="${profileName || 'SAFi'} Avatar" class="w-6 h-6 rounded-lg flex-shrink-0">
      <span class="font-semibold truncate">${profileNameText}</span>
    `;
  }
}