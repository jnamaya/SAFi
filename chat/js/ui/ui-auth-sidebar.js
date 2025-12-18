// ui-auth-sidebar.js

import * as ui from './ui.js';
// Assuming formatRelativeTime is in utils.js
import { formatRelativeTime } from '../core/utils.js';
import { iconMenuDots } from './ui-render-constants.js';

/**
 * Icons (for pin feature)
 */
const iconPin = `<svg class="w-4 h-4 text-current" fill="currentColor" viewBox="0 0 24 24"><path d="M17 11.5c.34-.14.65-.3.94-.48l-2.61-2.61c-.18.29-.34.6-.48.94L17 11.5zM14 17.5V21h-2v-3.5L8.5 14H5v-2h3.5L12 8.5V5h2v3.5l3.5 3.5H21v2h-3.5L14 17.5zM14 3c0-1.1-.9-2-2-2s-2 .9-2 2 .9 2 2 2 2-.9 2-2zM4 22c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"/></svg>`;
const iconUnpin = `<svg class="w-4 h-4 text-current" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 4v1m0 5v1m0 5v1m0 5v1M7 4h10a2 2 0 012 2v10a2 2 0 01-2 2H7a2 2 0 01-2-2V6a2 2 0 012-2z"/></svg>`;
const iconPinFilled = `<svg class="w-4 h-4 text-current" fill="currentColor" viewBox="0 0 24 24"><path d="M17 11.5c.34-.14.65-.3.94-.48l-2.61-2.61c-.18.29-.34.6-.48.94L17 11.5zM14 17.5V21h-2v-3.5L8.5 14H5v-2h3.5L12 8.5V5h2v3.5l3.5 3.5H21v2h-3.5L14 17.5zM14 3c0-1.1-.9-2-2-2s-2 .9-2 2 .9 2 2 2 2-.9 2-2zM4 22c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"/></svg>`;

// --- NEW: Search Icon ---
const iconSearch = `<svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>`;

// --- NEW: Profile Cache ---
// Allows us to look up avatars for custom profiles by name
let _knownProfiles = [];

export function setKnownProfiles(profiles) {
  _knownProfiles = profiles || [];
}

/**
 * Updates the entire sidebar UI based on the user's login status.
 * @param {object | null} user - The user object, or null if logged out.
 */
export function updateUIForAuthState(user) {
  ui._ensureElements();

  const pic = user?.picture || user?.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user?.name ? user.name.charAt(0) : 'U'}`;
  const name = user?.name || 'Guest';

  if (user) {
    ui.elements.loginView.classList.add('hidden');

    ui.elements.sidebarContainer.innerHTML = `
        <div id="sidebar-overlay" class="fixed inset-0 bg-black/50 z-30 hidden md:hidden transition-opacity duration-300 opacity-0"></div>
        <aside id="sidebar" class="hidden md:flex fixed inset-y-0 left-0 w-72 bg-white dark:bg-black text-neutral-900 dark:text-white flex-col z-40 transform -translate-x-full transition-transform duration-300 ease-in-out md:translate-x-0 h-full border-r border-gray-200 dark:border-gray-800">
          
          <!-- Header Area -->
          <div class="p-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between shrink-0">
            <div class="flex items-center gap-3">
              <div class="app-logo h-10 w-10">
                <img src="assets/logo.png" alt="SAFi Logo" class="rounded-lg w-full h-full object-contain" onerror="this.onerror=null; this.src='https://placehold.co/40x40/22c55e/FFFFFF?text=S'">
              </div>
              <p class="app-tagline text-gray-500 dark:text-gray-400 leading-tight">The Governance Engine For AI</p>
            </div>

            <button id="sidebar-close-btn" type="button" aria-label="Close sidebar" class="md:hidden p-2 rounded-full hover:bg-neutral-100 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400 transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
          </div>
          
          <!-- Search Bar Area -->
          <div class="px-4 pt-4 shrink-0">
             <div class="relative">
                <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    ${iconSearch}
                </div>
                <input type="text" id="convo-search-input" placeholder="Search chats..." class="w-full pl-10 pr-3 py-2 bg-gray-100 dark:bg-neutral-900 border-none rounded-lg text-sm text-gray-900 dark:text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-green-500 focus:outline-none transition-shadow">
             </div>
          </div>

          <div class="p-4 shrink-0">
            <button id="new-chat-button" type="button" class="w-full bg-green-600 text-white font-semibold px-4 py-2.5 rounded-lg hover:bg-green-700 transition-colors flex items-center justify-center gap-2 shadow-sm hover:shadow-md">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
              New Chat
            </button>
          </div>
           
          <nav id="convo-list" aria-label="Conversation history" class="flex-1 overflow-y-auto p-2 space-y-0.5 custom-scrollbar min-h-0">
            <!-- Content generated by renderConvoList -->
          </nav>
          
            <div id="user-profile-container" class="p-4 border-t border-gray-200 dark:border-gray-800 shrink-0 space-y-3">
              <!-- User Info Block (Generic, non-clickable for now, or could link to profile) -->
              <div class="flex items-center gap-3">
                <img src="${pic}" alt="User Avatar" class="w-10 h-10 rounded-full bg-gray-200 dark:bg-gray-700">
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-semibold truncate text-neutral-900 dark:text-white" title="${name}">${name}</p>
                  <p class="text-xs text-neutral-500 dark:text-neutral-400 truncate" title="${user.email}">${user.email}</p>
                </div>
              </div>

              <!-- Dedicated Control Panel Button -->
              <button id="control-panel-btn" type="button" class="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-3 py-2 rounded-lg transition-colors text-sm font-medium shadow-sm" aria-label="Open Control Panel">
                 <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                 <span>Control Panel</span>
              </button>
            </div>
        </aside>
    `;

    // --- Search Logic ---
    const searchInput = document.getElementById('convo-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase();
        const links = document.querySelectorAll('#convo-list > a'); // Select top level links only

        links.forEach(link => {
          const titleEl = link.querySelector('.convo-title');
          const title = titleEl ? titleEl.textContent.toLowerCase() : '';
          // Simple filter: toggle hidden class
          if (title.includes(term)) {
            link.classList.remove('hidden');
          } else {
            link.classList.add('hidden');
          }
        });

        // Optional: Hide headers if all their children are hidden
        const headers = document.querySelectorAll('#convo-list h3');
        headers.forEach(header => {
          let next = header.nextElementSibling;
          let hasVisible = false;
          while (next && next.tagName === 'A') {
            if (!next.classList.contains('hidden')) {
              hasVisible = true;
              break;
            }
            next = next.nextElementSibling;
          }
          header.style.display = hasVisible ? 'block' : 'none';
        });
      });
    }

    // Event Listeners
    const closeBtn = document.getElementById('sidebar-close-btn');
    if (closeBtn) {
      closeBtn.addEventListener('click', ui.closeSidebar);
    }

    const overlay = document.getElementById('sidebar-overlay');
    if (overlay) {
      overlay.addEventListener('click', ui.closeSidebar);
    }

  } else {
    ui.elements.sidebarContainer.innerHTML = '';
    ui.elements.loginView.classList.remove('hidden');
    ui.elements.chatView.classList.add('hidden');
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
  }
}

/**
 * Creates the dropdown menu for conversation actions (Rename/Delete/Pin).
 */
function createDropdownMenu(convoId, isPinned, handlers) {
  const menu = document.createElement('div');
  menu.className = 'convo-menu-dropdown fixed z-50 w-36 bg-white dark:bg-neutral-800 rounded-lg shadow-xl border border-neutral-200 dark:border-neutral-700 p-1';
  menu.dataset.menuId = convoId;

  const pinButton = document.createElement('button');
  pinButton.className = "flex items-center gap-3 w-full text-left px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-md";
  pinButton.innerHTML = isPinned ?
    `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 19V6a2 2 0 012-2h10a2 2 0 012 2v13M12 4v16m-4-8h8"></path></svg>
    <span>Unpin</span>` :
    `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 19V6a2 2 0 012-2h10a2 2 0 012 2v13M12 4v16m-4-8h8"></path></svg>
    <span>Pin</span>`;
  pinButton.addEventListener('click', (e) => {
    e.stopPropagation();
    ui.closeAllConvoMenus();
    handlers.pinHandler(convoId, isPinned);
  });
  menu.appendChild(pinButton);

  const renameButton = document.createElement('button');
  renameButton.className = "flex items-center gap-3 w-full text-left px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-md";
  renameButton.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.5L15.232 5.232z"></path></svg>
    <span>Rename</span>
  `;
  renameButton.addEventListener('click', (e) => {
    e.stopPropagation();
    ui.closeAllConvoMenus();
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
    ui.closeAllConvoMenus();
    handlers.deleteHandler(convoId);
  });

  menu.appendChild(renameButton);
  menu.appendChild(deleteButton);
  menu.addEventListener('click', (e) => e.stopPropagation());

  return menu;
}

/**
 * Positions the dropdown menu relative to the conversation button.
 */
function positionDropdown(menu, button) {
  const rect = button.getBoundingClientRect();
  menu.style.top = 'auto';
  // Position menu above the button, with a small gap
  menu.style.bottom = `${window.innerHeight - rect.top + 4}px`;
  menu.style.left = 'auto';
  // Align right edges
  menu.style.right = `${window.innerWidth - rect.right - (rect.width / 2)}px`;
}

/**
 * Prepends a new conversation link to the conversation history list.
 */
export function prependConversationLink(convo, handlers) {
  ui._ensureElements();
  const convoList = document.getElementById('convo-list');
  if (!convoList) return;

  const link = renderConversationLink(convo, handlers);

  // Find the first non-header element or the top of the list
  let insertionPoint = convoList.querySelector('h3:nth-of-type(2)') || convoList.querySelector('h3:first-of-type');

  if (convo.is_pinned) {
    // Find the 'Pinned' header or create one
    let pinnedHeader = convoList.querySelector('h3:first-of-type');
    if (!pinnedHeader || pinnedHeader.textContent !== 'Pinned Conversations') {
      // Reloading the entire list is simpler for accurate sorting/headers
      convoList.prepend(link);
    } else {
      // Prepend after the pinned header
      pinnedHeader.after(link);
    }

  } else {
    // Prepend before the first non-pinned item, or after the 'All Conversations' header
    const allChatsHeader = convoList.querySelector('h3:last-of-type');
    if (allChatsHeader) {
      allChatsHeader.after(link);
    } else {
      // If no headers exist, just prepend
      convoList.prepend(link);
    }
  }
}

/**
 * Renders a single conversation link element.
 */
export function renderConversationLink(convo, handlers) {
  ui._ensureElements();
  const { switchHandler, renameHandler, deleteHandler, pinHandler } = handlers;

  const link = document.createElement('a');
  link.href = '#';
  link.dataset.id = convo.id;

  const innerContent = document.createElement('div');
  innerContent.className = 'convo-item-inner group relative flex items-start justify-between px-3 py-2 bg-white dark:bg-black hover:bg-neutral-100 dark:hover:bg-neutral-800 rounded-lg transition-colors duration-150';

  const pinHtml = convo.is_pinned ? `<span class="convo-pin-icon text-sm">${iconPinFilled}</span>` : '';

  innerContent.innerHTML = `
    <div class="flex items-center min-w-0 flex-1 pr-8">
        ${pinHtml}
        <div class="flex-1 min-w-0">
            <span class="convo-title truncate block text-sm font-medium">${convo.title || 'Untitled'}</span>
            <span class="convo-timestamp truncate block text-xs text-neutral-500 dark:text-neutral-400">
                ${convo.last_updated ? formatRelativeTime(convo.last_updated) : ''}
            </span>
        </div>
    </div>
    <button data-action="menu" class="convo-menu-button opacity-0 focus:opacity-100 menu-icon-hidden
                   absolute right-2 top-1/2 -translate-y-1/2 
                   p-1.5 rounded-full hover:bg-neutral-300 dark:hover:bg-neutral-700" 
            aria-label="Conversation options">
       ${iconMenuDots}
    </button>
  `;
  link.appendChild(innerContent);

  // --- Mobile Long Press & Tap Logic ---
  let longPressTimer = null;
  let isLongPress = false;
  const longPressDuration = 500; // 500ms for long press

  const handleTouchStart = (e) => {
    isLongPress = false;
    // Start a timer to check for long press
    longPressTimer = setTimeout(() => {
      isLongPress = true;
      const actionButton = innerContent.querySelector('button[data-action="menu"]');
      if (!actionButton) return;

      // Prevent default scroll/tap behavior
      e.preventDefault();
      e.stopPropagation();

      // Haptic feedback for mobile (assuming available)
      if (window.navigator && window.navigator.vibrate) {
        window.navigator.vibrate(50);
      }

      // Toggle menu
      if (document.querySelector('.convo-menu-dropdown')) {
        ui.closeAllConvoMenus();
        return;
      }
      const menu = createDropdownMenu(convo.id, convo.is_pinned, handlers);
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
      // If it was a long press, prevent the click/navigation
      e.preventDefault();
      e.stopPropagation();
    }
  };

  const handleTouchMove = () => {
    // If user starts scrolling, cancel the long press
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }
  };

  // Add touch event listeners for mobile on the inner content (long press/tap)
  innerContent.addEventListener('touchstart', handleTouchStart, { passive: false });
  innerContent.addEventListener('touchend', handleTouchEnd);
  innerContent.addEventListener('touchcancel', handleTouchMove);
  innerContent.addEventListener('touchmove', handleTouchMove);

  // Prevent desktop right-click menu
  link.addEventListener('contextmenu', (e) => {
    e.preventDefault();
  });

  // Standard click event for navigation or desktop menu
  link.addEventListener('click', (e) => {
    if (isLongPress) {
      // Prevent click if long press just happened
      e.preventDefault();
      e.stopPropagation();
      return;
    }

    const actionButton = e.target.closest('button[data-action="menu"]');

    if (actionButton) {
      // Click was on the menu button (desktop)
      e.preventDefault();
      e.stopPropagation();

      if (document.querySelector('.convo-menu-dropdown')) {
        ui.closeAllConvoMenus();
        return;
      }

      const menu = createDropdownMenu(convo.id, convo.is_pinned, handlers);
      positionDropdown(menu, actionButton);
      ui.setOpenDropdown(menu);

    } else {
      // Click was on the link itself (navigation)
      e.preventDefault();
      ui.closeAllConvoMenus();
      if (window.innerWidth < 768) ui.closeSidebar(); // Close sidebar on mobile nav
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
  // Target the top-level <a> elements
  document.querySelectorAll('#convo-list > a').forEach(link => {
    const inner = link.querySelector('.convo-item-inner');
    if (!link || !inner) return;

    const isActive = link.dataset.id === String(id);
    const title = link.querySelector('.convo-title');
    const timestamp = link.querySelector('.convo-timestamp');

    // Toggle active state classes on the inner element
    inner.classList.toggle('bg-green-600', isActive);
    inner.classList.toggle('text-white', isActive);
    inner.classList.toggle('dark:bg-green-600', isActive);
    inner.classList.toggle('dark:text-white', isActive);

    // Toggle inactive state classes (using bg-white dark:bg-black theme)
    inner.classList.toggle('bg-white', !isActive);
    inner.classList.toggle('dark:bg-black', !isActive);
    inner.classList.toggle('text-neutral-900', !isActive);
    inner.classList.toggle('dark:text-white', !isActive);
    inner.classList.toggle('hover:bg-neutral-100', !isActive);
    inner.classList.toggle('dark:hover:bg-neutral-800', !isActive);

    title?.classList.toggle('font-semibold', isActive);
    title?.classList.toggle('font-medium', !isActive);

    if (timestamp) {
      // Active state timestamp
      timestamp.classList.toggle('text-green-100', isActive);
      timestamp.classList.toggle('dark:text-green-100', isActive);

      // Inactive state timestamp
      timestamp.classList.toggle('text-neutral-500', !isActive);
      timestamp.classList.toggle('dark:text-neutral-400', !isActive);
    }
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
export function updateActiveProfileChip(profileNameOrObject) {
  ui._ensureElements();

  // Handle both string and object input
  let profileNameText = 'Default';
  let avatarUrl = '';

  if (typeof profileNameOrObject === 'string') {
    profileNameText = profileNameOrObject || 'Default';
    avatarUrl = getAvatarForProfile(profileNameText);
  } else if (profileNameOrObject && typeof profileNameOrObject === 'object') {
    profileNameText = profileNameOrObject.name || 'Default';
    // Use the object's avatar if present, otherwise look up by name
    avatarUrl = profileNameOrObject.avatar || getAvatarForProfile(profileNameText);
  }

  // --- CHANGED: "Persona:" to "Agent:" ---
  const textLabel = "Agent:";

  // Desktop chip
  if (ui.elements.activeProfileChip) {
    ui.elements.activeProfileChip.classList.add('flex', 'items-center', 'gap-2');
    ui.elements.activeProfileChip.innerHTML = `
      <span class="truncate flex-shrink-0">${textLabel}</span>
      <img src="${avatarUrl}" alt="${profileNameText} Avatar" class="w-5 h-5 rounded-md flex-shrink-0 object-cover">
      <span class="truncate">${profileNameText}</span>
    `;
  }

  // Mobile chip
  if (ui.elements.activeProfileChipMobile) {
    ui.elements.activeProfileChipMobile.classList.add('flex', 'items-center', 'gap-2', 'mx-auto', 'justify-center');
    ui.elements.activeProfileChipMobile.innerHTML = `
      <img src="${avatarUrl}" alt="${profileNameText} Avatar" class="w-4 h-4 rounded-lg flex-shrink-0 object-cover">
      <span class="font-semibold truncate">${profileNameText}</span>
    `;
  }

  // Update the main chat input placeholder
  if (ui.elements.messageInput) {
    ui.elements.messageInput.placeholder = `Ask ${profileNameText}`;
  }
}

/**
 * Helper function to get the correct avatar for a given profile name.
 * @param {string | null} profileName - The name of the profile.
 * @returns {string} - The URL to the avatar image.
 */
export function getAvatarForProfile(profileName) {
  const cleanName = profileName ? profileName.trim().toLowerCase() : null;

  // 1. Check known custom profiles first
  const customProfile = _knownProfiles.find(p => p.name && p.name.trim().toLowerCase() === cleanName);
  if (customProfile && customProfile.avatar) {
    return customProfile.avatar;
  }

  // 2. Fallback to hardcoded assets
  switch (cleanName) {
    case 'the contoso governance officer':
    case 'contoso governance officer':
    case 'the_contoso_governance_officer': // Sanitized backend key
      return 'assets/contoso.svg';
    case 'the fiduciary':
    case 'fiduciary':
    case 'the_fiduciary': // Sanitized backend key
      return 'assets/fiduciary.svg';
    case 'the health navigator':
    case 'health navigator':
    case 'the_health_navigator': // Sanitized backend key
      return 'assets/the_health_navigator.svg';
    case 'the socratic tutor':
    case 'socratic tutor':
    case 'the_socratic_tutor': // Sanitized backend key
    case 'the tutor':
      return 'assets/tutor.svg';
    case 'the vault':
    case 'vault':
    case 'the_vault': // Sanitized backend key
      return 'assets/vault.svg';
    case 'the negotiator':
    case 'negotiator':
    case 'the_negotiator': // Sanitized backend key
      return 'assets/negotiator.svg';
    case 'the bible scholar':
    case 'bible scholar':
    case 'the_bible_scholar': // Sanitized backend key
      return 'assets/bible_scholar.svg';
    case 'the safi guide':
    case 'the_safi_guide': // Sanitized backend key
    default:
      return 'assets/safi.svg';
  }
}

/**
 * --- NEW: Agent Selector Logic (Bottom Input) ---
 */

/**
 * Initializes the agent selector in the chat input area.
 * @param {Array} profiles - List of available profiles.
 * @param {string} activeProfileKey - The key of the currently active profile.
 * @param {Function} onSelect - Callback when a profile is selected (key) => void.
 */
export function initAgentSelector(profiles, activeProfileKey, onSelect) {
  ui._ensureElements();
  const { agentSelectorBtn, agentSelectorDropdown, agentSelectorContainer } = ui.elements;

  if (!agentSelectorBtn || !agentSelectorDropdown) return;

  // 1. Render Options
  renderAgentSelectorOptions(profiles, activeProfileKey, onSelect);

  // 2. Set Initial Button State
  const activeProfile = profiles.find(p => p.key === activeProfileKey) || profiles[0];
  updateAgentSelectorButton(activeProfile);

  // 3. Toggle Logic
  // Remove old listener if any (simple way: clone node, or just assume init is called once)
  // We'll stick to adding a listener, assuming init is called once per app load or we handle deduping
  agentSelectorBtn.onclick = (e) => {
    e.stopPropagation();
    const isHidden = agentSelectorDropdown.classList.contains('hidden');
    if (isHidden) {
      showAgentSelector();
    } else {
      hideAgentSelector();
    }
  };

  // Close when clicking outside
  document.addEventListener('click', (e) => {
    if (!agentSelectorContainer.contains(e.target)) {
      hideAgentSelector();
    }
  });
}

function showAgentSelector() {
  ui._ensureElements();
  const { agentSelectorDropdown } = ui.elements;
  if (agentSelectorDropdown) agentSelectorDropdown.classList.remove('hidden');
}

function hideAgentSelector() {
  ui._ensureElements();
  const { agentSelectorDropdown } = ui.elements;
  if (agentSelectorDropdown) agentSelectorDropdown.classList.add('hidden');
}

/**
 * Updates the text and icon of the selector button.
 */
export function updateAgentSelectorButton(profile) {
  ui._ensureElements();
  const { agentSelectorBtn } = ui.elements;
  if (!agentSelectorBtn) return;
  if (!profile) return;

  const avatarUrl = profile.avatar || getAvatarForProfile(profile.name);

  agentSelectorBtn.innerHTML = `
    <img src="${avatarUrl}" alt="Agent" class="w-4 h-4 rounded-full object-cover">
    <span>${profile.name}</span>
    <svg class="w-3 h-3 text-neutral-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
    </svg>
  `;
}

/**
 * Renders the list of agents in the dropdown.
 */
function renderAgentSelectorOptions(profiles, activeProfileKey, onSelect) {
  ui._ensureElements();
  const { agentSelectorDropdown, agentSelectorBtn } = ui.elements;
  if (!agentSelectorDropdown) return;

  agentSelectorDropdown.innerHTML = '';

  // Header
  const header = document.createElement('div');
  header.className = 'px-3 py-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider bg-neutral-50 dark:bg-neutral-800/50';
  header.textContent = 'Select Agent';
  agentSelectorDropdown.appendChild(header);

  profiles.forEach(profile => {
    const avatarUrl = profile.avatar || getAvatarForProfile(profile.name);
    const isActive = profile.key === activeProfileKey;

    const btn = document.createElement('button');
    btn.className = `w-full text-left px-4 py-2 text-sm flex items-center gap-3 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors ${isActive ? 'bg-neutral-50 dark:bg-neutral-800 font-medium text-green-600 dark:text-green-500' : 'text-neutral-700 dark:text-neutral-300'}`;

    btn.innerHTML = `
      <img src="${avatarUrl}" alt="${profile.name}" class="w-4 h-4 rounded-full object-cover">
      <span class="truncate">${profile.name}</span>
      ${isActive ? `<svg class="w-4 h-4 ml-auto text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>` : ''}
    `;

    btn.onclick = () => {
      // Optimistic update
      updateAgentSelectorButton(profile);
      hideAgentSelector();

      // Re-render options to update checkmarks
      renderAgentSelectorOptions(profiles, profile.key, onSelect);

      // Trigger callback
      if (onSelect) onSelect(profile.key);
    };

    agentSelectorDropdown.appendChild(btn);
  });
}
