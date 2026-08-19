// ui-auth-sidebar.js

import * as ui from './ui.js';
import { escapeHtml } from '../core/utils.js';
import { iconMenuDots } from './ui-render-constants.js';
import { updateAgentLabel, closeComposerMenu } from './ui-composer-menu.js';
import { agentMark, normalizeAgentName } from './ui-agent-mark.js';
import { initAttentionBadge } from './ui-attention.js';

/**
 * Icons (for pin feature)
 */
const iconPin = `<svg class="w-4 h-4 text-current" fill="currentColor" viewBox="0 0 24 24"><path d="M17 11.5c.34-.14.65-.3.94-.48l-2.61-2.61c-.18.29-.34.6-.48.94L17 11.5zM14 17.5V21h-2v-3.5L8.5 14H5v-2h3.5L12 8.5V5h2v3.5l3.5 3.5H21v2h-3.5L14 17.5zM14 3c0-1.1-.9-2-2-2s-2 .9-2 2 .9 2 2 2 2-.9 2-2zM4 22c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"/></svg>`;
const iconUnpin = `<svg class="w-4 h-4 text-current" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 4v1m0 5v1m0 5v1m0 5v1M7 4h10a2 2 0 012 2v10a2 2 0 01-2 2H7a2 2 0 01-2-2V6a2 2 0 012-2z"/></svg>`;
const iconPinFilled = `<svg class="w-4 h-4 text-current" fill="currentColor" viewBox="0 0 24 24"><path d="M17 11.5c.34-.14.65-.3.94-.48l-2.61-2.61c-.18.29-.34.6-.48.94L17 11.5zM14 17.5V21h-2v-3.5L8.5 14H5v-2h3.5L12 8.5V5h2v3.5l3.5 3.5H21v2h-3.5L14 17.5zM14 3c0-1.1-.9-2-2-2s-2 .9-2 2 .9 2 2 2 2-.9 2-2zM4 22c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"/></svg>`;

// --- NEW: Search Icon ---
const iconSearch = `<svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>`;

// --- Collapsed-rail "recent conversations" popup ---
// The collapsed rail has no room for the conversation list, so this floats a
// small menu built from the (still-in-DOM, off-screen) #convo-list links.
// Clicking an item forwards to the real link, so it runs the exact same
// switch-conversation path as the expanded list — no duplicated load logic.
let _recentPopupEl = null;

function _closeRecentPopup() {
    if (_recentPopupEl) { _recentPopupEl.remove(); _recentPopupEl = null; }
    document.removeEventListener('click', _onRecentOutside, true);
    document.removeEventListener('keydown', _onRecentEsc);
}

function _onRecentOutside(e) {
    if (_recentPopupEl && !_recentPopupEl.contains(e.target) && !e.target.closest('#rail-recent')) {
        _closeRecentPopup();
    }
}

function _onRecentEsc(e) {
    if (e.key === 'Escape') _closeRecentPopup();
}

function _openRecentConvoPopup(anchorBtn) {
    _closeRecentPopup();
    const links = Array.from(document.querySelectorAll('#convo-list a[data-id]')).slice(0, 15);

    const pop = document.createElement('div');
    _recentPopupEl = pop;
    pop.className = 'recent-convo-popup fixed z-[80] w-64 max-h-[70vh] overflow-y-auto custom-scrollbar rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 shadow-lg py-1';

    const header = document.createElement('div');
    header.className = 'px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-neutral-400 dark:text-neutral-500';
    header.textContent = 'Recent';
    pop.appendChild(header);

    if (!links.length) {
        const empty = document.createElement('div');
        empty.className = 'px-3 py-2 text-sm text-neutral-400';
        empty.textContent = 'No conversations yet.';
        pop.appendChild(empty);
    } else {
        links.forEach(link => {
            const titleEl = link.querySelector('.convo-title');
            const title = (titleEl ? titleEl.textContent : '').trim() || 'Untitled';
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'block w-full text-left px-3 py-2 text-sm text-neutral-700 dark:text-neutral-200 hover:bg-neutral-100 dark:hover:bg-neutral-800 truncate';
            b.textContent = title;
            b.title = title;
            b.addEventListener('click', () => { _closeRecentPopup(); link.click(); });
            pop.appendChild(b);
        });
    }

    document.body.appendChild(pop);

    // Position beside the rail button, clamped to the viewport.
    const r = anchorBtn.getBoundingClientRect();
    pop.style.left = (r.right + 8) + 'px';
    pop.style.top = r.top + 'px';
    const pr = pop.getBoundingClientRect();
    if (pr.bottom > window.innerHeight - 8) {
        pop.style.top = Math.max(8, window.innerHeight - 8 - pr.height) + 'px';
    }

    // Defer binding so this same click doesn't immediately close it.
    setTimeout(() => {
        document.addEventListener('click', _onRecentOutside, true);
        document.addEventListener('keydown', _onRecentEsc);
    }, 0);
}

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

  const pic = user?.picture || user?.avatar || `https://placehold.co/40x40/16a34a/FFFFFF?text=${user?.name ? user.name.charAt(0) : 'U'}`;
  const name = user?.name || 'Guest';

  if (user) {
    ui.elements.loginView.classList.add('hidden');
    // The chat's left offset is CSS's job now (--sidebar-w in styles.css), so
    // this only has to say "a sidebar exists". It used to add the matching
    // md:ml-* utility, which put the width in a second place and then a third
    // and a fourth as handlers copied the line.
    document.documentElement.classList.add('has-sidebar');

    ui.elements.sidebarContainer.innerHTML = `
        <div id="sidebar-overlay" class="fixed inset-0 bg-black/50 z-30 hidden md:hidden transition-opacity duration-300 opacity-0"></div>
        <aside id="sidebar" class="hidden md:flex fixed inset-y-0 left-0 w-full bg-white dark:bg-[#000000] text-neutral-900 dark:text-white flex-col z-40 transform -translate-x-full transition-transform duration-300 ease-in-out md:translate-x-0 h-full border-r border-gray-200 dark:border-neutral-800">
          
          <!-- Header Area -->
          <div class="px-3 py-3 flex items-center justify-between shrink-0">
            <div class="flex items-center gap-3">
              <div class="app-logo h-10 w-10">
                <img src="assets/logo-white.png" alt="SAFi Logo" class="rounded-lg w-full h-full object-contain block dark:hidden" onerror="this.onerror=null; this.src='https://placehold.co/32x32/22c55e/FFFFFF?text=S'">
                <img src="assets/logo.png" alt="SAFi Logo" class="rounded-lg w-full h-full object-contain hidden dark:block" onerror="this.onerror=null; this.src='https://placehold.co/32x32/22c55e/FFFFFF?text=S'">
              </div>
              <span class="font-semibold text-lg tracking-tight">SAFi</span>
            </div>

            <div class="flex items-center">
              <!-- Collapse sidebar (desktop only) -->
              <button data-sidebar-toggle type="button" aria-label="Collapse sidebar" title="Collapse sidebar" class="hidden md:inline-flex p-1.5 rounded-md hover:bg-neutral-200 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"></rect><path stroke-linecap="round" stroke-linejoin="round" d="M9 4v16"></path></svg>
              </button>

              <button id="sidebar-close-btn" type="button" aria-label="Close sidebar" class="md:hidden p-1.5 rounded-md hover:bg-neutral-200 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7"></path></svg>
              </button>
            </div>
          </div>
          
          <!-- Search Bar Area -->
          <div class="px-3 pt-2 shrink-0 space-y-2">
             <!-- Search Bar (Styled as a flat menu item) -->
             <div class="relative group cursor-text">
                <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-neutral-500 group-hover:text-neutral-700 dark:group-hover:text-neutral-300">
                    ${iconSearch}
                </div>
                <input type="text" id="convo-search-input" placeholder="Search" class="w-full pl-9 pr-3 py-2 bg-transparent rounded-md text-sm text-neutral-900 dark:text-white placeholder-neutral-500 font-medium hover:bg-neutral-100 dark:hover:bg-neutral-900 focus:bg-neutral-100 dark:focus:bg-neutral-900 focus:outline-none transition-colors">
             </div>

             <!-- New Chat Button -->
             <button id="new-chat-button" type="button" class="w-full flex items-center justify-start gap-3 bg-green-600 hover:bg-green-700 text-white shadow-sm px-4 py-2.5 rounded-full transition-colors text-sm font-bold">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>
                <span>New Conversation</span>
             </button>

             <!-- Saved Content -->
             <button id="saved-content-button" type="button" class="w-full flex items-center justify-start gap-3 px-3 py-2 rounded-md text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-900 transition-colors">
                <svg class="w-4 h-4 text-neutral-500" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"></path></svg>
                <span>Saved</span>
             </button>
          </div>

          <!-- Conversation List -->
          <nav id="convo-list" aria-label="Conversation history" class="flex-1 overflow-y-auto px-2 py-2 mt-2 space-y-0.5 custom-scrollbar min-h-0">
            <!-- Content generated by renderConvoList -->
          </nav>
          
            <div class="px-3 py-3 shrink-0">
              <!-- User Info Block (Now acts as Control Panel trigger) -->
              <button id="control-panel-btn" type="button" class="w-full flex items-center justify-between px-2 py-2 rounded-md hover:bg-neutral-100 dark:hover:bg-neutral-900 transition-colors text-left group" aria-label="Open Control Panel">
                <div class="flex items-center gap-3 min-w-0">
                  <img src="${pic}" alt="User Avatar" class="w-8 h-8 rounded-full bg-neutral-200 dark:bg-neutral-800 shrink-0">
                  <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium truncate text-neutral-900 dark:text-white leading-tight" title="${name}">${name}</p>
                    <p class="text-[11px] text-neutral-500 truncate mt-0.5" title="${user.email}">${user.email}</p>
                  </div>
                </div>
                <!-- Gear: this row opens the Control Panel, and three dots said
                     "more options" rather than "configuration". Same icon as the
                     collapsed rail's settings button, so the affordance reads the
                     same in both states. -->
                <div class="shrink-0 text-neutral-400 group-hover:text-neutral-600 dark:text-neutral-500 dark:group-hover:text-neutral-300 transition-colors">
                  <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.6"><path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" /><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" /></svg>
                </div>
              </button>
            </div>
        </aside>

        <!-- Collapsed-state icon rail (desktop only; CSS displays it while
             html.sidebar-collapsed is set). Buttons delegate to the real
             sidebar controls, which stay in the DOM while collapsed — the
             sidebar is translated off-screen, not removed — so there is
             exactly one implementation of each action. -->
        <div id="sidebar-rail"
          class="hidden fixed inset-y-0 left-0 w-14 z-40 flex-col items-center py-3 bg-white dark:bg-black border-r border-gray-200 dark:border-neutral-800">
          <!-- Brand mark that IS the expand control: the logo at rest, the
               expand-panel icon on hover or keyboard focus, one click to
               expand. Merging them means one control in the top slot instead
               of a logo shadowed by a separate toggle below it. Same assets
               and light/dark swap as the expanded header. -->
          <button data-sidebar-toggle type="button" aria-label="Expand sidebar" title="Expand sidebar"
            class="group relative h-9 w-9 mb-2 flex items-center justify-center rounded-lg hover:bg-neutral-200 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400 transition-colors">
            <span class="app-logo h-9 w-9 transition-opacity group-hover:opacity-0 group-focus-visible:opacity-0">
              <img src="assets/logo-white.png" alt="SAFi Logo" class="rounded-lg w-full h-full object-contain block dark:hidden" onerror="this.onerror=null; this.src='https://placehold.co/32x32/22c55e/FFFFFF?text=S'">
              <img src="assets/logo.png" alt="SAFi Logo" class="rounded-lg w-full h-full object-contain hidden dark:block" onerror="this.onerror=null; this.src='https://placehold.co/32x32/22c55e/FFFFFF?text=S'">
            </span>
            <svg class="absolute inset-0 m-auto w-5 h-5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"></rect><path stroke-linecap="round" stroke-linejoin="round" d="M9 4v16"></path></svg>
          </button>
          <button id="rail-new-chat" type="button" aria-label="New conversation" title="New conversation"
            class="mt-2 w-9 h-9 flex items-center justify-center rounded-full bg-green-600 hover:bg-green-700 text-white shadow-sm transition-colors">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>
          </button>
          <!-- Recent conversations without expanding: opens a popup listing the
               current convo links, so a collapsed rail can still jump chats. -->
          <button id="rail-recent" type="button" aria-label="Recent conversations" title="Recent conversations"
            class="mt-2 w-10 h-10 flex items-center justify-center rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400 transition-colors">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.86 9.86 0 01-4-.8L3 21l1.2-3.6A7.9 7.9 0 013 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path></svg>
          </button>
          <div class="flex-1"></div>
          <button id="rail-account" type="button" aria-label="Open Control Panel" title="${name}"
            class="p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">
            <img src="${pic}" alt="User Avatar" class="w-8 h-8 rounded-full bg-neutral-200 dark:bg-neutral-800">
          </button>
          <button id="rail-settings" type="button" aria-label="Open Control Panel" title="Settings"
            class="mt-1 p-2 rounded-md hover:bg-neutral-200 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400 transition-colors">
            <svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.6"><path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" /><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" /></svg>
          </button>
        </div>
    `;

    // Rail wiring: forward to the real controls rather than re-implementing
    // them. If new-chat or the control panel ever changes behaviour, the rail
    // follows for free.
    document.getElementById('rail-new-chat')?.addEventListener('click', () =>
        document.getElementById('new-chat-button')?.click());
    document.getElementById('rail-account')?.addEventListener('click', () => {
        // The avatar goes to YOUR profile; the gear goes to the panel's default
        // tab. Same two-step pattern the profile chip already uses: open the
        // panel, then click the profile tab's nav button.
        document.getElementById('control-panel-btn')?.click();
        document.getElementById('nav-profile')?.click();
    });
    document.getElementById('rail-settings')?.addEventListener('click', () =>
        document.getElementById('control-panel-btn')?.click());
    document.getElementById('rail-recent')?.addEventListener('click', (e) => {
        e.stopPropagation();
        if (_recentPopupEl) { _closeRecentPopup(); return; }
        _openRecentConvoPopup(e.currentTarget);
    });

    // Inbox count pill on the Control Panel nav (backlog 57): starts polling
    // once a user is signed in. The tab itself renders on entry.
    initAttentionBadge();

    // --- Search Logic ---
    const searchInput = document.getElementById('convo-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase();
        const links = document.querySelectorAll('#convo-list a[data-id]'); // Loose + project-folder links

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
    // No sidebar when logged out — drop the reserved margin so the login view
    // centers on the actual viewport instead of sitting 128px right of center.
    document.documentElement.classList.remove('has-sidebar');
    ui.elements.loginView.classList.remove('hidden');
    ui.elements.chatView.classList.add('hidden');
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
  }
}

// --- Shared menu primitives (used by conversation + project dropdowns) ---

const iconPinMenu = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 4h6l-1 6 3 3v2H7v-2l3-3-1-6z M12 15v5"></path></svg>`;
const iconRenameMenu = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.5L15.232 5.232z"></path></svg>`;
const iconTrashMenu = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>`;
const iconFolderMenu = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"></path></svg>`;
const iconChevronRightSmall = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"></path></svg>`;
const iconChevronLeftSmall = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"></path></svg>`;
const iconRemoveCircle = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10 14L21 3m-1 7v8a1 1 0 01-1 1H5a1 1 0 01-1-1V6a1 1 0 011-1h8"></path></svg>`;

function buildMenuContainer(menuId) {
  const menu = document.createElement('div');
  menu.className = 'convo-menu-dropdown fixed z-50 w-52 bg-white dark:bg-neutral-800 rounded-xl shadow-2xl ring-1 ring-black/[0.06] dark:ring-white/10 p-1.5';
  menu.dataset.menuId = menuId;
  menu.addEventListener('click', (e) => e.stopPropagation());
  return menu;
}

/**
 * Builds one menu row. `label` is rendered as text (safe for user-supplied names).
 */
function menuItem({ icon = '', label, danger = false, trailing = '', onClick }) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = [
    'flex items-center gap-3 w-full text-left px-2.5 py-2 text-sm font-medium rounded-lg transition-colors',
    danger
      ? 'text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10'
      : 'text-neutral-700 dark:text-neutral-200 hover:bg-neutral-100 dark:hover:bg-neutral-700/60',
  ].join(' ');

  if (icon) {
    const iconSpan = document.createElement('span');
    iconSpan.className = `shrink-0 ${danger ? '' : 'text-neutral-400 dark:text-neutral-500'}`;
    iconSpan.innerHTML = icon;
    btn.appendChild(iconSpan);
  }
  const labelSpan = document.createElement('span');
  labelSpan.className = 'flex-1 truncate';
  labelSpan.textContent = label;
  btn.appendChild(labelSpan);
  if (trailing) {
    const t = document.createElement('span');
    t.className = 'shrink-0 text-neutral-400 dark:text-neutral-500';
    t.innerHTML = trailing;
    btn.appendChild(t);
  }
  btn.addEventListener('click', (e) => { e.stopPropagation(); onClick(e); });
  return btn;
}

function menuDivider() {
  const d = document.createElement('div');
  d.className = 'my-1 mx-1 border-t border-neutral-200/80 dark:border-neutral-700/70';
  return d;
}

function menuHeader(label, onBack) {
  const row = document.createElement('button');
  row.type = 'button';
  row.className = 'flex items-center gap-1.5 w-full px-2 py-1.5 mb-0.5 text-[11px] font-semibold text-neutral-500 uppercase tracking-wider hover:text-neutral-800 dark:hover:text-neutral-200 transition-colors';
  if (onBack) row.innerHTML = iconChevronLeftSmall;
  const span = document.createElement('span');
  span.textContent = label;
  row.appendChild(span);
  if (onBack) row.addEventListener('click', (e) => { e.stopPropagation(); onBack(); });
  else row.disabled = true;
  return row;
}

/**
 * Renders the main conversation menu into an (existing) container element.
 */
function populateConvoMenu(menu, convoId, isPinned, handlers, currentProjectId) {
  menu.innerHTML = '';

  menu.appendChild(menuItem({
    icon: iconPinMenu,
    label: isPinned ? 'Unpin' : 'Pin',
    onClick: () => { ui.closeAllConvoMenus(); handlers.pinHandler(convoId, isPinned); },
  }));

  menu.appendChild(menuItem({
    icon: iconRenameMenu,
    label: 'Rename',
    onClick: () => {
      ui.closeAllConvoMenus();
      const titleEl = document.querySelector(`a[data-id="${convoId}"] .convo-title`);
      handlers.renameHandler(convoId, titleEl ? titleEl.textContent : '');
    },
  }));

  if (typeof handlers.moveHandler === 'function') {
    menu.appendChild(menuItem({
      icon: iconFolderMenu,
      label: 'Move to',
      trailing: iconChevronRightSmall,
      onClick: () => renderMoveSubmenu(menu, convoId, isPinned, currentProjectId, handlers),
    }));
  }

  menu.appendChild(menuDivider());

  menu.appendChild(menuItem({
    icon: iconTrashMenu,
    label: 'Delete',
    danger: true,
    onClick: () => { ui.closeAllConvoMenus(); handlers.deleteHandler(convoId); },
  }));
}

/**
 * Creates the dropdown menu for conversation actions (Pin / Rename / Move / Delete).
 */
function createDropdownMenu(convoId, isPinned, handlers, currentProjectId = null) {
  const menu = buildMenuContainer(convoId);
  populateConvoMenu(menu, convoId, isPinned, handlers, currentProjectId);
  return menu;
}

/**
 * Swaps the menu contents for a project picker (with a back arrow to the main menu).
 */
function renderMoveSubmenu(menu, convoId, isPinned, currentProjectId, handlers) {
  const projects = Array.isArray(handlers.projects) ? handlers.projects : [];
  menu.innerHTML = '';

  menu.appendChild(menuHeader('Move to folder',
    () => populateConvoMenu(menu, convoId, isPinned, handlers, currentProjectId)));

  if (currentProjectId) {
    menu.appendChild(menuItem({
      icon: iconRemoveCircle,
      label: 'Remove from folder',
      onClick: () => handlers.moveHandler(convoId, null),
    }));
    if (projects.some(p => p.id !== currentProjectId)) menu.appendChild(menuDivider());
  }

  const targets = projects.filter(p => p.id !== currentProjectId);
  if (targets.length === 0 && !currentProjectId) {
    const empty = document.createElement('p');
    empty.className = 'px-2.5 py-2 text-xs text-neutral-400 italic';
    empty.textContent = 'No other folders';
    menu.appendChild(empty);
  } else {
    targets.forEach(p => menu.appendChild(menuItem({
      icon: iconFolderMenu,
      label: p.name || 'Untitled',
      onClick: () => handlers.moveHandler(convoId, p.id),
    })));
  }
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
 * Icons for project folders.
 */
const iconChevronRight = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>`;
const iconChevronDown = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>`;
const iconFolder = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"></path></svg>`;
const iconPlusSmall = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>`;

/**
 * Dropdown menu for a project folder (Rename / Delete).
 */
function createProjectMenu(project, projectHandlers) {
  const menu = buildMenuContainer(`project-${project.id}`);

  menu.appendChild(menuItem({
    icon: iconPlusSmall,
    label: 'New conversation',
    onClick: () => { ui.closeAllConvoMenus(); projectHandlers.newChatHandler(project.id); },
  }));
  menu.appendChild(menuItem({
    icon: iconRenameMenu,
    label: 'Rename',
    onClick: () => { ui.closeAllConvoMenus(); projectHandlers.renameHandler(project.id, project.name); },
  }));
  menu.appendChild(menuDivider());
  menu.appendChild(menuItem({
    icon: iconTrashMenu,
    label: 'Delete folder',
    danger: true,
    onClick: () => { ui.closeAllConvoMenus(); projectHandlers.deleteHandler(project.id, project.name); },
  }));

  return menu;
}

/**
 * Renders a collapsible project folder containing its conversation links.
 */
export function renderProjectFolder(project, convos, isExpanded, projectHandlers, convoHandlers) {
  ui._ensureElements();

  const wrap = document.createElement('div');
  wrap.className = 'mb-0.5';
  wrap.dataset.projectId = project.id;

  const header = document.createElement('div');
  header.className = 'project-folder-header group relative flex items-center justify-between px-2 py-1.5 rounded-md hover:bg-black/[0.05] dark:hover:bg-white/[0.06] transition-colors';

  // Toggle (chevron + folder + name + count)
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'flex items-center gap-2 min-w-0 flex-1 text-left text-neutral-700 dark:text-neutral-300';
  toggle.innerHTML = `
    <span class="shrink-0 text-neutral-500">${isExpanded ? iconChevronDown : iconChevronRight}</span>
    <span class="shrink-0 text-neutral-500">${iconFolder}</span>
    <span class="project-folder-name truncate text-sm font-medium"></span>
    <span class="shrink-0 text-xs text-neutral-400">${convos.length || ''}</span>
  `;
  // User-controlled name: set as text to avoid HTML injection.
  toggle.querySelector('.project-folder-name').textContent = project.name || 'Untitled';
  toggle.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    projectHandlers.toggleHandler(project.id);
  });

  const actions = document.createElement('div');
  actions.className = 'flex items-center gap-0.5 shrink-0';

  const newChatBtn = document.createElement('button');
  newChatBtn.type = 'button';
  newChatBtn.title = 'New conversation in folder';
  newChatBtn.className = 'p-1 rounded-full opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-neutral-300 dark:hover:bg-neutral-700 text-neutral-500';
  newChatBtn.innerHTML = iconPlusSmall;
  newChatBtn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    projectHandlers.newChatHandler(project.id);
  });

  const menuBtn = document.createElement('button');
  menuBtn.type = 'button';
  menuBtn.title = 'Folder options';
  menuBtn.className = 'p-1 rounded-full opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-neutral-300 dark:hover:bg-neutral-700 text-neutral-500';
  menuBtn.innerHTML = iconMenuDots;
  menuBtn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (document.querySelector('.convo-menu-dropdown')) {
      ui.closeAllConvoMenus();
      return;
    }
    const menu = createProjectMenu(project, projectHandlers);
    positionDropdown(menu, menuBtn);
    ui.setOpenDropdown(menu);
  });

  actions.appendChild(newChatBtn);
  actions.appendChild(menuBtn);
  header.appendChild(toggle);
  header.appendChild(actions);
  wrap.appendChild(header);

  if (isExpanded) {
    const body = document.createElement('div');
    body.className = 'pl-3 ml-2 border-l border-neutral-200 dark:border-neutral-800';
    if (convos.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'px-3 py-1.5 text-xs text-neutral-400 italic';
      empty.textContent = 'No conversations yet';
      body.appendChild(empty);
    } else {
      convos.forEach(convo => body.appendChild(renderConversationLink(convo, convoHandlers)));
    }
    wrap.appendChild(body);
  }

  return wrap;
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
  innerContent.className = 'convo-item-inner group relative flex items-center justify-between px-3 py-1.5 rounded-md transition-colors duration-150 hover:bg-black/[0.05] dark:hover:bg-white/[0.06] text-neutral-600 dark:text-neutral-400 font-medium my-0.5';

  const pinHtml = convo.is_pinned ? `<span class="convo-pin-icon text-sm">${iconPinFilled}</span>` : '';

  // Which agent this conversation was with — the one fact that makes a
  // multi-agent product's history different from a chat app's. Reuses the
  // same avatar chain as the rest of the sidebar (org avatar -> builtin ->
  // generated monogram), so custom and unknown agents both render something.
  // Older rows with no audited turn have no profile_name; they get no mark
  // rather than a misleading placeholder.
  const markHtml = convo.profile_name
    ? `<img src="${getAvatarForProfile(convo.profile_name)}" alt="" aria-hidden="true" class="w-4 h-4 rounded-md object-cover shrink-0 mr-2">`
    : '';

  innerContent.innerHTML = `
    <div class="flex items-center min-w-0 flex-1 pr-8">
        ${pinHtml}
        ${markHtml}
        <div class="flex-1 min-w-0">
            <span class="convo-title truncate block text-sm font-medium" title="${(convo.title || 'Untitled').replace(/"/g, '&quot;')}">${convo.title || 'Untitled'}</span>
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
      const menu = createDropdownMenu(convo.id, convo.is_pinned, handlers, convo.project_id || null);
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

      const menu = createDropdownMenu(convo.id, convo.is_pinned, handlers, convo.project_id || null);
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

    // -- Active State --
    if (isActive) {
      // Active row: subtle raised fill + green left accent (styled in CSS via .is-active)
      inner.className = 'convo-item-inner is-active group relative flex items-center justify-between px-3 py-1.5 rounded-md transition-all duration-200 text-neutral-900 dark:text-neutral-100 font-bold my-0.5';

      if (timestamp) {
        // Timestamp text made slightly lighter than main text
        timestamp.className = "convo-timestamp truncate block text-xs text-neutral-500 dark:text-neutral-500";
      }
    } else {
      inner.className = 'convo-item-inner group relative flex items-center justify-between px-3 py-1.5 rounded-md transition-colors duration-150 hover:bg-black/[0.05] dark:hover:bg-white/[0.06] text-neutral-600 dark:text-neutral-400 font-medium my-0.5';

      if (title) title.className = `convo-title truncate block text-sm ${isActive ? 'font-semibold' : 'font-medium'}`;
    }

    // Timestamp color is consistent now (neutral grey)
    if (timestamp) {
      timestamp.className = "convo-timestamp truncate block text-xs text-neutral-500 dark:text-neutral-400";
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
 * Updates the chip displaying the currently active profile/agent.
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

  // --- CHANGED: "Agent:" to "Agent:" ---
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
    ui.elements.messageInput.placeholder = `Message ${profileNameText}`;
  }
}

/**
 * Helper function to get the correct avatar for a given profile name.
 * @param {string | null} profileName - The name of the profile.
 * @returns {string} - The URL to the avatar image.
 */
export function getAvatarForProfile(profileName) {
  const cleanName = profileName ? profileName.trim().toLowerCase() : null;

  // Accept the agent's storage KEY as well as its display name. Conversation
  // rows carry the key (chat_history.profile_name is set from the profile key,
  // e.g. org_xxxx_policy_officer) while this lookup matched display names only
  // — so an org's uploaded avatar never showed in the conversation list, and
  // the fallback monogram was generated from the ugly key instead of the name.
  const customProfile = _knownProfiles.find(p =>
    (p.name && p.name.trim().toLowerCase() === cleanName) ||
    (p.key && String(p.key).trim().toLowerCase() === cleanName));

  // 1. An avatar the org supplied for its own agent always wins.
  if (customProfile && customProfile.avatar) {
    return customProfile.avatar;
  }

  // Everything below reasons about the DISPLAY name, whichever form came in.
  const displayName = (customProfile && customProfile.name) || profileName;

  // 2. The one real mark. It is not a agent portrait, which is why it
  //    survives: safi.svg is the product wordmark, which The SAFi Guide is
  //    entitled to wear.
  //
  //    Every other agent gets a generated monogram — see ui-agent-mark.js for
  //    why the illustrated faces were removed. Note that unknown agents now get
  //    a monogram rather than falling through to safi.svg: an org's custom agent
  //    should not appear wearing the vendor's logo.
  const key = normalizeAgentName(displayName);
  if (key === 'safi guide' || !key) return 'assets/safi.svg';

  return agentMark(displayName);
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
  const { agentSelectorDropdown } = ui.elements;
  if (!agentSelectorDropdown) return;

  renderAgentSelectorOptions(profiles, activeProfileKey, onSelect);

  const activeProfile = profiles.find(p => p.key === activeProfileKey) || profiles[0];
  updateAgentSelectorButton(activeProfile);
}

function hideAgentSelector() {
  // The list no longer hides itself — it is a section of the + panel, so
  // choosing an agent dismisses the panel around it.
  closeComposerMenu();
}

/**
 * Updates the text and icon of the selector button.
 */
export function updateAgentSelectorButton(profile) {
  if (!profile) return;
  const avatarUrl = profile.avatar || getAvatarForProfile(profile.name);
  updateAgentLabel(profile.name, avatarUrl);
}

/**
 * Renders the list of agents in the dropdown.
 */
function renderAgentSelectorOptions(profiles, activeProfileKey, onSelect) {
  ui._ensureElements();
  const { agentSelectorDropdown, agentSelectorBtn } = ui.elements;
  if (!agentSelectorDropdown) return;

  agentSelectorDropdown.innerHTML = '';

  // No header here any more: this list is a section of the + panel, and the
  // panel prints "Agents" above it. Two labels for one list read as two lists.

  profiles.forEach(profile => {
    const avatarUrl = profile.avatar || getAvatarForProfile(profile.name);
    const isActive = profile.key === activeProfileKey;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.setAttribute('role', 'menuitemradio');
    btn.setAttribute('aria-checked', String(isActive));
    btn.className = `w-full text-left px-3 py-2 rounded-lg text-sm flex items-center gap-3 transition-colors ${isActive ? 'bg-neutral-50 dark:bg-neutral-800 font-medium text-green-600 dark:text-green-500' : 'text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-800'}`;

    // Second line: the governing policy when there is one — the single most
    // useful fact when choosing between agents — else a trimmed description,
    // else the tier. Keeps the row honest about what governs the pick.
    const hasPolicy = profile.policy_id && profile.policy_id !== 'standalone';
    let subtitleRaw = (hasPolicy && profile.policy_name)
        ? profile.policy_name
        : (profile.description || '').trim()
          || (profile.is_custom === false ? 'Built-in agent' : 'Standalone agent');
    // An agent reaching this user through a grant rather than the visibility
    // tier says so: the reader should know it was shared with them.
    if (profile.shared_via_grant) subtitleRaw = `Shared with you · ${subtitleRaw}`;

    // Agent names are org-authored free text and land in an attribute and in
    // markup; the avatar URL and subtitle are org-supplied too.
    const safeName = escapeHtml(profile.name || '');
    const safeSub = escapeHtml(subtitleRaw);
    btn.innerHTML = `
      <img src="${escapeHtml(avatarUrl || '')}" alt="" class="w-7 h-7 rounded-full object-cover shrink-0 ${isActive ? 'ring-2 ring-green-600/60' : ''}">
      <span class="min-w-0 flex-1">
        <span class="block truncate" title="${safeName}">${safeName}</span>
        <span class="block truncate text-xs font-normal ${isActive ? 'text-neutral-500 dark:text-neutral-400' : 'text-neutral-400 dark:text-neutral-500'}" title="${safeSub}">${safeSub}</span>
      </span>
      ${isActive ? `<svg class="w-4 h-4 ml-auto shrink-0 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>` : ''}
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