import * as ui from './ui.js';
import { escapeHtml } from '../core/utils.js';
import { iconMenuDots } from './ui-render-constants.js';
import { updateAgentLabel, closeComposerMenu } from './ui-composer-menu.js';
import { agentMark, normalizeAgentName } from './ui-agent-mark.js';
import { initAttentionBadge } from './ui-attention.js';

const iconPin = `<svg class="w-4 h-4 text-current" fill="currentColor" viewBox="0 0 24 24"><path d="M17 11.5c.34-.14.65-.3.94-.48l-2.61-2.61c-.18.29-.34.6-.48.94L17 11.5zM14 17.5V21h-2v-3.5L8.5 14H5v-2h3.5L12 8.5V5h2v3.5l3.5 3.5H21v2h-3.5L14 17.5zM14 3c0-1.1-.9-2-2-2s-2 .9-2 2 .9 2 2 2 2-.9 2-2zM4 22c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"/></svg>`;
const iconUnpin = `<svg class="w-4 h-4 text-current" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 4v1m0 5v1m0 5v1m0 5v1M7 4h10a2 2 0 012 2v10a2 2 0 01-2 2H7a2 2 0 01-2-2V6a2 2 0 012-2z"/></svg>`;
const iconPinFilled = `<svg class="w-4 h-4 text-current" fill="currentColor" viewBox="0 0 24 24"><path d="M17 11.5c.34-.14.65-.3.94-.48l-2.61-2.61c-.18.29-.34.6-.48.94L17 11.5zM14 17.5V21h-2v-3.5L8.5 14H5v-2h3.5L12 8.5V5h2v3.5l3.5 3.5H21v2h-3.5L14 17.5zM14 3c0-1.1-.9-2-2-2s-2 .9-2 2 .9 2 2 2 2-.9 2-2zM4 22c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"/></svg>`;

const iconSearch = `<svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>`;

const iconLogo = (cls) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="29 29 42 42" class="${cls}">
  <circle cx="50" cy="36" r="7" fill="#16a34a"/>
  <circle cx="64" cy="46" r="7" fill="#16a34a"/>
  <circle cx="58" cy="64" r="7" fill="#16a34a"/>
  <circle cx="42" cy="64" r="7" fill="#16a34a"/>
  <circle cx="36" cy="46" r="7" fill="#16a34a"/>
  <circle cx="50" cy="52" r="6" fill="#4ade80"/>
</svg>`;

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
    const links = Array.from(document.querySelectorAll('#convo-list a[data-id]'))
        .sort((a, b) => (b.dataset.updated || '').localeCompare(a.dataset.updated || ''))
        .slice(0, 15);

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

    const r = anchorBtn.getBoundingClientRect();
    pop.style.left = (r.right + 8) + 'px';
    pop.style.top = r.top + 'px';
    const pr = pop.getBoundingClientRect();
    if (pr.bottom > window.innerHeight - 8) {
        pop.style.top = Math.max(8, window.innerHeight - 8 - pr.height) + 'px';
    }

    setTimeout(() => {
        document.addEventListener('click', _onRecentOutside, true);
        document.addEventListener('keydown', _onRecentEsc);
    }, 0);
}

let _knownProfiles = [];

export function setKnownProfiles(profiles) {
  _knownProfiles = profiles || [];
}

export function updateUIForAuthState(user) {
  ui._ensureElements();

  const init = encodeURIComponent((user?.name ? user.name.charAt(0) : 'U').toUpperCase());
  const pic = user?.picture || user?.avatar || `data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40' viewBox='0 0 40 40'><rect width='40' height='40' fill='%2316a34a'/><text x='50%25' y='54%25' dominant-baseline='middle' text-anchor='middle' fill='%23FFFFFF' font-family='sans-serif' font-size='18' font-weight='600'>${init}</text></svg>`;
  const name = user?.name || 'Guest';
  const identity = user?.email || user?.username || user?.name || 'Local account';

  if (user) {
    ui.elements.loginView.classList.add('hidden');
    document.documentElement.classList.add('has-sidebar');

    ui.elements.sidebarContainer.innerHTML = `
        <div id="sidebar-overlay" class="fixed inset-0 bg-black/50 z-30 hidden md:hidden transition-opacity duration-300 opacity-0"></div>
        <aside id="sidebar" class="hidden md:flex fixed inset-y-0 left-0 w-full bg-white dark:bg-[#000000] text-neutral-900 dark:text-white flex-col z-40 transform -translate-x-full transition-transform duration-300 ease-in-out md:translate-x-0 h-full border-r border-gray-200 dark:border-neutral-800">
          
          <!-- Header Area -->
          <div class="px-3 py-3 flex items-center justify-between shrink-0">
            <div class="flex items-center gap-3">
              <div class="app-logo h-6 w-6 text-neutral-900 dark:text-white">
                ${iconLogo('w-full h-full')}
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
                    <p class="text-[11px] text-neutral-500 truncate mt-0.5" title="${identity}">${identity}</p>
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
            <span class="app-logo h-6 w-6 transition-opacity group-hover:opacity-0 group-focus-visible:opacity-0 text-neutral-900 dark:text-white">
              ${iconLogo('w-full h-full')}
            </span>
            <svg class="absolute inset-0 m-auto w-6 h-6 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"></rect><path stroke-linecap="round" stroke-linejoin="round" d="M9 4v16"></path></svg>
          </button>
          <button id="rail-new-chat" type="button" aria-label="New conversation" title="New conversation"
            class="mt-2 w-7 h-7 flex items-center justify-center rounded-full bg-green-600 hover:bg-green-700 text-white shadow-sm transition-colors">
             <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15"></path></svg>
          </button>
          <!-- Recent conversations without expanding: opens a popup listing the
               current convo links, so a collapsed rail can still jump chats. -->
          <button id="rail-recent" type="button" aria-label="Recent conversations" title="Recent conversations"
            class="mt-2 w-8 h-8 flex items-center justify-center rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400 transition-colors">
             <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z"></path></svg>
          </button>
          <div class="flex-1"></div>
          <button id="rail-account" type="button" aria-label="Open Control Panel" title="${name}"
            class="p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors">
            <img src="${pic}" alt="User Avatar" class="w-8 h-8 rounded-full bg-neutral-200 dark:bg-neutral-800">
          </button>
          <button id="rail-settings" type="button" aria-label="Open Control Panel" title="Settings"
            class="mt-1 p-2 rounded-md hover:bg-neutral-200 dark:hover:bg-neutral-800 text-neutral-500 dark:text-neutral-400 transition-colors">
             <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.6"><path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" /><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" /></svg>
          </button>
        </div>
    `;

    document.getElementById('rail-new-chat')?.addEventListener('click', () =>
        document.getElementById('new-chat-button')?.click());
    document.getElementById('rail-account')?.addEventListener('click', () => {
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

    initAttentionBadge();

    const searchInput = document.getElementById('convo-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase();
        const links = document.querySelectorAll('#convo-list a[data-id]');

        links.forEach(link => {
          const titleEl = link.querySelector('.convo-title');
          const title = titleEl ? titleEl.textContent.toLowerCase() : '';
          if (title.includes(term)) {
            link.classList.remove('hidden');
          } else {
            link.classList.add('hidden');
          }
        });

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
    document.documentElement.classList.remove('has-sidebar');
    ui.elements.loginView.classList.remove('hidden');
    ui.elements.chatView.classList.add('hidden');
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
  }
}


const iconPinMenu = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 4h6l-1 6 3 3v2H7v-2l3-3-1-6z M12 15v5"></path></svg>`;
const iconRenameMenu = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.5L15.232 5.232z"></path></svg>`;
const iconTrashMenu = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>`;
const iconFolderMenu = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"></path></svg>`;
const iconChevronRightSmall = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"></path></svg>`;
const iconChevronLeftSmall = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"></path></svg>`;
const iconRemoveCircle = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10 14L21 3m-1 7v8a1 1 0 01-1 1H5a1 1 0 01-1-1V6a1 1 0 011-1h8"></path></svg>`;
const iconShareMenu = `<svg class="w-[18px] h-[18px]" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8.684 13.342a3 3 0 100-2.684m0 2.684a3 3 0 100 2.684m0-2.684l6.632 3.316m0-9L8.684 10.658M18 6a3 3 0 11-6 0 3 3 0 016 0zm0 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>`;

function buildMenuContainer(menuId) {
  const menu = document.createElement('div');
  menu.className = 'convo-menu-dropdown fixed z-50 w-52 bg-white dark:bg-neutral-800 rounded-xl shadow-2xl ring-1 ring-black/[0.06] dark:ring-white/10 p-1.5';
  menu.dataset.menuId = menuId;
  menu.addEventListener('click', (e) => e.stopPropagation());
  return menu;
}

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

  if (typeof handlers.shareHandler === 'function') {
    menu.appendChild(menuItem({
      icon: iconShareMenu,
      label: 'Share',
      onClick: () => {
        ui.closeAllConvoMenus();
        const titleEl = document.querySelector(`a[data-id="${convoId}"] .convo-title`);
        handlers.shareHandler(convoId, titleEl ? titleEl.textContent : '');
      },
    }));
  }

  if (typeof handlers.unshareHandler === 'function') {
    menu.appendChild(menuItem({
      icon: iconSharedMark,
      label: 'Remove from shared with me',
      danger: true,
      onClick: () => {
        ui.closeAllConvoMenus();
        const titleEl = document.querySelector(`a[data-id="${convoId}"] .convo-title`);
        handlers.unshareHandler(convoId, titleEl ? titleEl.textContent : '');
      },
    }));
  } else {
    menu.appendChild(menuDivider());
    menu.appendChild(menuItem({
      icon: iconTrashMenu,
      label: 'Delete',
      danger: true,
      onClick: () => { ui.closeAllConvoMenus(); handlers.deleteHandler(convoId); },
    }));
  }
}

function createDropdownMenu(convoId, isPinned, handlers, currentProjectId = null) {
  const menu = buildMenuContainer(convoId);
  populateConvoMenu(menu, convoId, isPinned, handlers, currentProjectId);
  return menu;
}

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

function positionDropdown(menu, button) {
  const rect = button.getBoundingClientRect();
  menu.style.top = 'auto';
  menu.style.bottom = `${window.innerHeight - rect.top + 4}px`;
  menu.style.left = 'auto';
  menu.style.right = `${window.innerWidth - rect.right - (rect.width / 2)}px`;
}


const iconChevronRight = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>`;
const iconChevronDown = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>`;
const iconFolder = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"></path></svg>`;
const iconPeople = `<svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"></path></svg>`;
const iconSharedMark = `<svg class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8.684 13.342a3 3 0 100-2.684m0 2.684a3 3 0 100 2.684m0-2.684l6.632 3.316m0-9L8.684 10.658M18 6a3 3 0 11-6 0 3 3 0 016 0zm0 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>`;
const iconPlusSmall = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg>`;

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
  if (typeof projectHandlers.shareHandler === 'function') {
    menu.appendChild(menuItem({
      icon: iconShareMenu,
      label: 'Share',
      onClick: () => { ui.closeAllConvoMenus(); projectHandlers.shareHandler(project.id, project.name); },
    }));
  }
  menu.appendChild(menuDivider());
  menu.appendChild(menuItem({
    icon: iconTrashMenu,
    label: 'Delete folder',
    danger: true,
    onClick: () => { ui.closeAllConvoMenus(); projectHandlers.deleteHandler(project.id, project.name); },
  }));

  return menu;
}

export function renderSidebarSection(label, count, isExpanded, onToggle, opts = {}) {
  ui._ensureElements();

  const wrap = document.createElement('div');
  wrap.className = 'mb-0.5';

  const header = document.createElement('div');
  header.className = 'group relative flex items-center px-2 py-1.5 rounded-md hover:bg-black/[0.05] dark:hover:bg-white/[0.06] transition-colors';

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'flex items-center gap-2 min-w-0 flex-1 text-left text-neutral-700 dark:text-neutral-300';
  toggle.innerHTML = `
    <span class="shrink-0 text-neutral-500">${isExpanded ? iconChevronDown : iconChevronRight}</span>
    <span class="shrink-0 text-neutral-500">${opts.icon || iconPeople}</span>
    <span class="sidebar-section-name truncate text-sm font-medium"></span>
    <span class="shrink-0 text-xs text-neutral-400">${count || ''}</span>
  `;
  toggle.querySelector('.sidebar-section-name').textContent = label;
  if (opts.title) toggle.title = opts.title;
  toggle.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    onToggle();
  });
  header.appendChild(toggle);
  wrap.appendChild(header);

  let body = null;
  if (isExpanded) {
    body = document.createElement('div');
    body.className = 'pl-3 ml-2 border-l border-neutral-200 dark:border-neutral-800';
    wrap.appendChild(body);
  }

  return { wrap, body };
}

export function renderProjectFolder(project, convos, isExpanded, projectHandlers, convoHandlers, opts = {}) {
  ui._ensureElements();

  const wrap = document.createElement('div');
  wrap.className = 'mb-0.5';
  wrap.dataset.projectId = project.id;

  const header = document.createElement('div');
  header.className = 'project-folder-header group relative flex items-center justify-between px-2 py-1.5 rounded-md hover:bg-black/[0.05] dark:hover:bg-white/[0.06] transition-colors';

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'flex items-center gap-2 min-w-0 flex-1 text-left text-neutral-700 dark:text-neutral-300';
  toggle.innerHTML = `
    <span class="shrink-0 text-neutral-500">${isExpanded ? iconChevronDown : iconChevronRight}</span>
    <span class="shrink-0 text-neutral-500">${iconFolder}</span>
    <span class="project-folder-name truncate text-sm font-medium"></span>
    ${opts.shared ? `<span class="shrink-0 text-neutral-400" title="Shared with others">${iconSharedMark}</span>` : ''}
    <span class="shrink-0 text-xs text-neutral-400">${convos.length || ''}</span>
  `;
  const nameSpan = toggle.querySelector('.project-folder-name');
  nameSpan.textContent = project.name || 'Untitled';
  if (opts.readOnly) {
    toggle.title = opts.ownerName ? `Shared by ${opts.ownerName}` : 'Shared with you';
  }
  toggle.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    projectHandlers.toggleHandler(project.id);
  });

  header.appendChild(toggle);

  if (!opts.readOnly) {
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
    header.appendChild(actions);
  } else if (typeof projectHandlers.unshareHandler === 'function') {
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.title = 'Remove from shared with me';
    removeBtn.className = 'p-1 rounded-full opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-neutral-300 dark:hover:bg-neutral-700 text-neutral-500';
    removeBtn.innerHTML = iconSharedMark;
    removeBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      projectHandlers.unshareHandler(project.id, project.name);
    });
    header.appendChild(removeBtn);
  }
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

export function renderConversationLink(convo, handlers) {
  ui._ensureElements();
  const { switchHandler, renameHandler, deleteHandler, pinHandler } = handlers;
  const isShared = !!(handlers.sharedConvoIds && handlers.sharedConvoIds.has(convo.id));

  const link = document.createElement('a');
  link.href = '#';
  link.dataset.id = convo.id;
  link.dataset.updated = convo.last_updated || convo.created_at || '';

  const innerContent = document.createElement('div');
  innerContent.className = 'convo-item-inner group relative flex items-center justify-between px-3 py-1.5 rounded-md transition-colors duration-150 hover:bg-black/[0.05] dark:hover:bg-white/[0.06] text-neutral-600 dark:text-neutral-400 font-medium my-0.5';

  const pinHtml = convo.is_pinned ? `<span class="convo-pin-icon text-sm">${iconPinFilled}</span>` : '';

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
        ${isShared ? `<span class="shrink-0 ml-1 text-neutral-400" title="Shared with others">${iconSharedMark}</span>` : ''}
    </div>
    <button data-action="menu" class="convo-menu-button opacity-0 focus:opacity-100 menu-icon-hidden
                   absolute right-2 top-1/2 -translate-y-1/2 
                   p-1.5 rounded-full hover:bg-neutral-300 dark:hover:bg-neutral-700" 
            aria-label="Conversation options">
       ${iconMenuDots}
    </button>
  `;
  link.appendChild(innerContent);

  let longPressTimer = null;
  let isLongPress = false;
  const longPressDuration = 500;

  const handleTouchStart = (e) => {
    isLongPress = false;
    longPressTimer = setTimeout(() => {
      isLongPress = true;
      const actionButton = innerContent.querySelector('button[data-action="menu"]');
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

  innerContent.addEventListener('touchstart', handleTouchStart, { passive: false });
  innerContent.addEventListener('touchend', handleTouchEnd);
  innerContent.addEventListener('touchcancel', handleTouchMove);
  innerContent.addEventListener('touchmove', handleTouchMove);

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

      if (document.querySelector('.convo-menu-dropdown')) {
        ui.closeAllConvoMenus();
        return;
      }

      const menu = createDropdownMenu(convo.id, convo.is_pinned, handlers, convo.project_id || null);
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

export function setActiveConvoLink(id) {
  ui._ensureElements();
  document.querySelectorAll('#convo-list > a').forEach(link => {
    const inner = link.querySelector('.convo-item-inner');
    if (!link || !inner) return;

    const isActive = link.dataset.id === String(id);
    const title = link.querySelector('.convo-title');
    const timestamp = link.querySelector('.convo-timestamp');

    if (isActive) {
      inner.className = 'convo-item-inner is-active group relative flex items-center justify-between px-3 py-1.5 rounded-md transition-all duration-200 text-neutral-900 dark:text-neutral-100 font-bold my-0.5';

      if (timestamp) {
        timestamp.className = "convo-timestamp truncate block text-xs text-neutral-500 dark:text-neutral-500";
      }
    } else {
      inner.className = 'convo-item-inner group relative flex items-center justify-between px-3 py-1.5 rounded-md transition-colors duration-150 hover:bg-black/[0.05] dark:hover:bg-white/[0.06] text-neutral-600 dark:text-neutral-400 font-medium my-0.5';

      if (title) title.className = `convo-title truncate block text-sm ${isActive ? 'font-semibold' : 'font-medium'}`;
    }

    if (timestamp) {
      timestamp.className = "convo-timestamp truncate block text-xs text-neutral-500 dark:text-neutral-400";
    }
  });
}

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
  setBrowserTabTitle(newTitle);
}

function setBrowserTabTitle(title) {
  const clean = String(title || '').replace(/[\x00-\x1F\x7F]/g, '').trim();
  if (!clean || clean === 'Untitled' || clean === 'SAFi') {
    document.title = 'SAFi';
    return;
  }
  document.title = ('SAFi \u00B7 ' + clean).slice(0, 120);
}

export function updateActiveProfileChip(profileNameOrObject) {
  ui._ensureElements();

  if (!profileNameOrObject || (typeof profileNameOrObject === 'object' && !profileNameOrObject.name && !profileNameOrObject.key)) {
    if (ui.elements.activeProfileChip) {
      ui.elements.activeProfileChip.classList.add('flex', 'items-center', 'gap-2');
      ui.elements.activeProfileChip.innerHTML = `
        <span class="truncate flex-shrink-0 text-neutral-400">Agent: None</span>
      `;
    }
    if (ui.elements.activeProfileChipMobile) {
      ui.elements.activeProfileChipMobile.classList.add('flex', 'items-center', 'gap-2', 'mx-auto', 'justify-center');
      ui.elements.activeProfileChipMobile.innerHTML = `
        <span class="font-semibold truncate text-neutral-400">No Agent</span>
      `;
    }
    if (ui.elements.messageInput) {
      ui.elements.messageInput.placeholder = 'No agents currently available';
    }
    return;
  }

  let profileNameText = 'Default';
  let avatarUrl = '';

  if (typeof profileNameOrObject === 'string') {
    profileNameText = profileNameOrObject || 'Default';
    avatarUrl = getAvatarForProfile(profileNameText);
  } else if (profileNameOrObject && typeof profileNameOrObject === 'object') {
    profileNameText = profileNameOrObject.name || 'Default';
    avatarUrl = profileNameOrObject.avatar || getAvatarForProfile(profileNameText);
  }

  const textLabel = "Agent:";

  if (ui.elements.activeProfileChip) {
    ui.elements.activeProfileChip.classList.add('flex', 'items-center', 'gap-2');
    ui.elements.activeProfileChip.innerHTML = `
      <span class="truncate flex-shrink-0">${textLabel}</span>
      <img src="${avatarUrl}" alt="${profileNameText} Avatar" class="w-5 h-5 rounded-md flex-shrink-0 object-cover">
      <span class="truncate">${profileNameText}</span>
    `;
  }

  if (ui.elements.activeProfileChipMobile) {
    ui.elements.activeProfileChipMobile.classList.add('flex', 'items-center', 'gap-2', 'mx-auto', 'justify-center');
    ui.elements.activeProfileChipMobile.innerHTML = `
      <img src="${avatarUrl}" alt="${profileNameText} Avatar" class="w-4 h-4 rounded-lg flex-shrink-0 object-cover">
      <span class="font-semibold truncate">${profileNameText}</span>
    `;
  }

  if (ui.elements.messageInput) {
    ui.elements.messageInput.placeholder = `Message ${profileNameText}`;
  }
}

export function getAvatarForProfile(profileName) {
  const cleanName = profileName ? profileName.trim().toLowerCase() : null;

  const customProfile = _knownProfiles.find(p =>
    (p.name && p.name.trim().toLowerCase() === cleanName) ||
    (p.key && String(p.key).trim().toLowerCase() === cleanName));

  if (customProfile && customProfile.avatar) {
    return customProfile.avatar;
  }

  const displayName = (customProfile && customProfile.name) || profileName;

  const key = normalizeAgentName(displayName);
  if (key === 'safi guide' || !key) return 'assets/safi.svg';

  return agentMark(displayName);
}


export function initAgentSelector(profiles, activeProfileKey, onSelect) {
  ui._ensureElements();
  const { agentSelectorDropdown } = ui.elements;
  if (!agentSelectorDropdown) return;

  renderAgentSelectorOptions(profiles, activeProfileKey, onSelect);

  const activeProfile = (profiles && profiles.find(p => p.key === activeProfileKey)) || (profiles && profiles[0]) || null;
  updateAgentSelectorButton(activeProfile);
}

function hideAgentSelector() {
  closeComposerMenu();
}

export function updateAgentSelectorButton(profile) {
  if (!profile) {
    updateAgentLabel('None');
    return;
  }
  const avatarUrl = profile.avatar || getAvatarForProfile(profile.name);
  updateAgentLabel(profile.name, avatarUrl);
}

function renderAgentSelectorOptions(profiles, activeProfileKey, onSelect) {
  ui._ensureElements();
  const { agentSelectorDropdown, agentSelectorBtn } = ui.elements;
  if (!agentSelectorDropdown) return;

  agentSelectorDropdown.innerHTML = '';

  if (!profiles || profiles.length === 0) {
    agentSelectorDropdown.innerHTML = '<div class="px-3 py-2 text-xs text-neutral-400">No agents available</div>';
    return;
  }


  profiles.forEach(profile => {
    const avatarUrl = profile.avatar || getAvatarForProfile(profile.name);
    const isActive = profile.key === activeProfileKey;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.setAttribute('role', 'menuitemradio');
    btn.setAttribute('aria-checked', String(isActive));
    btn.className = `w-full text-left px-3 py-2 rounded-lg text-sm flex items-center gap-3 transition-colors ${isActive ? 'bg-neutral-50 dark:bg-neutral-800 font-medium text-green-600 dark:text-green-500' : 'text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-800'}`;

    const hasPolicy = profile.policy_id && profile.policy_id !== 'standalone';
    let subtitleRaw = (hasPolicy && profile.policy_name)
        ? profile.policy_name
        : (profile.description || '').trim()
          || (profile.is_custom === false ? 'Built-in agent' : 'Standalone agent');
    if (profile.shared_via_grant) subtitleRaw = `Shared with you · ${subtitleRaw}`;

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
      updateAgentSelectorButton(profile);
      hideAgentSelector();

      renderAgentSelectorOptions(profiles, profile.key, onSelect);

      if (onSelect) onSelect(profile.key);
    };

    agentSelectorDropdown.appendChild(btn);
  });
}
