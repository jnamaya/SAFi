
/**
 * convo-menu-fix.js
 * Drop-in patch for conversation kebab menu on desktop + mobile.
 * - Positions dropdown near the button using viewport clamping
 * - Prevents outside-click race with action items
 * - Closes menus on resize and sidebar scroll
 * - Provides default Rename/Delete handlers with graceful fallbacks
 *
 * Usage:
 *   1) Include this file after your main scripts, near </body>:
 *        <script src="convo-menu-fix.js"></script>
 *   2) Ensure each conversation row has:
 *        <div class="convo-item" data-convo-id="...">
 *          ...
 *          <button class="convo-menu-button" aria-label="Conversation menu">⋮</button>
 *        </div>
 *      If your button already exists, just add/confirm the classes above.
 *   3) Optional hooks your app can define:
 *        window.onConversationRename = async (id, newTitle) => { ... }
 *        window.onConversationDelete = async (id) => { ... }
 */
(function () {
  const DROPDOWN_CLASS = 'convo-menu-dropdown';
  const LIST_ID = 'convo-list'; // scroll container id if you have one
  let openDropdown = null;

  function closeOpenDropdown() {
    if (openDropdown && openDropdown.parentNode) {
      openDropdown.parentNode.removeChild(openDropdown);
    }
    openDropdown = null;
  }

  function makeDropdown(convoId) {
    const menu = document.createElement('div');
    menu.className = `${DROPDOWN_CLASS} fixed z-50 shadow-lg rounded-xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 text-sm overflow-hidden`;
    menu.innerHTML = `
      <button data-action="rename" class="block w-full text-left px-4 py-2 hover:bg-neutral-100 dark:hover:bg-neutral-700">Rename</button>
      <button data-action="delete" class="block w-full text-left px-4 py-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30">Delete</button>
    `;
    // Prevent outside-click handler from firing first
    menu.addEventListener('click', (e) => e.stopPropagation());

    menu.addEventListener('click', async (e) => {
      const btn = e.target.closest('button[data-action]');
      if (!btn) return;
      const action = btn.getAttribute('data-action');
      try {
        if (action === 'rename') {
          let newTitle = prompt('Rename conversation to:');
          if (!newTitle || !newTitle.trim()) return;
          newTitle = newTitle.trim();
          if (typeof window.onConversationRename === 'function') {
            await window.onConversationRename(convoId, newTitle);
          } else {
            // Fallback: dispatch a DOM CustomEvent for your app to catch
            document.dispatchEvent(new CustomEvent('convo:rename', { detail: { id: convoId, title: newTitle }}));
          }
        } else if (action === 'delete') {
          const ok = confirm('Delete this conversation? This cannot be undone.');
          if (!ok) return;
          if (typeof window.onConversationDelete === 'function') {
            await window.onConversationDelete(convoId);
          } else {
            document.dispatchEvent(new CustomEvent('convo:delete', { detail: { id: convoId }}));
          }
        }
      } finally {
        closeOpenDropdown();
      }
    });
    return menu;
  }

  function positionDropdown(menu, triggerRect) {
    // Show invisibly to measure
    menu.style.top = '0px';
    menu.style.left = '0px';
    menu.style.visibility = 'hidden';
    document.body.appendChild(menu);

    const menuW = menu.offsetWidth || 160;
    const menuH = menu.offsetHeight || 96;

    let top = triggerRect.bottom + 8;      // below by default
    let left = triggerRect.right - menuW;  // right-aligned to button

    // Flip above if it overflows bottom
    if (top + menuH > window.innerHeight) {
      top = triggerRect.top - menuH - 8;
    }
    // Clamp horizontally
    if (left < 8) left = 8;
    if (left + menuW > window.innerWidth - 8) left = window.innerWidth - 8 - menuW;

    menu.style.top = `${Math.max(8, top)}px`;
    menu.style.left = `${left}px`;
    menu.style.right = 'auto';
    menu.style.bottom = 'auto';
    menu.style.visibility = 'visible';
  }

  function onKebabClick(e) {
    const btn = e.currentTarget;
    e.stopPropagation(); // so outside-click doesn’t immediately close
    const item = btn.closest('.convo-item');
    if (!item) return;
    const convoId = item.getAttribute('data-convo-id') || item.dataset.id || '';

    // Toggle behavior
    if (openDropdown && openDropdown.__ownerBtn === btn) {
      closeOpenDropdown();
      return;
    }
    closeOpenDropdown();

    const rect = btn.getBoundingClientRect();
    const menu = makeDropdown(convoId);
    menu.__ownerBtn = btn;
    openDropdown = menu;
    positionDropdown(menu, rect);
  }

  function wireKebabButtons(root = document) {
    const kebabs = root.querySelectorAll('.convo-menu-button');
    kebabs.forEach((btn) => {
      // Ensure only wired once
      if (btn.__wiredConvoMenuFix) return;
      btn.__wiredConvoMenuFix = true;
      btn.addEventListener('click', onKebabClick);
      // Improve desktop discoverability
      btn.classList.add('opacity-80');
      btn.addEventListener('mouseenter', () => btn.classList.add('opacity-100'));
      btn.addEventListener('mouseleave', () => btn.classList.remove('opacity-100'));
    });
  }

  function initObservers() {
    // Observe DOM changes to support dynamic list rendering
    const sidebar = document.getElementById('sidebar') || document;
    const mo = new MutationObserver((mutations) => {
      for (const m of mutations) {
        for (const n of m.addedNodes) {
          if (n.nodeType === 1) wireKebabButtons(n);
        }
      }
    });
    mo.observe(sidebar, { subtree: true, childList: true });
  }

  function initGlobalHandlers() {
    // Outside click
    document.addEventListener('click', (e) => {
      if (openDropdown) {
        const inside = e.target.closest('.' + DROPDOWN_CLASS) || e.target.closest('.convo-menu-button');
        if (!inside) closeOpenDropdown();
      }
    });
    // Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeOpenDropdown();
    });
    // Resize
    window.addEventListener('resize', closeOpenDropdown);
    // Sidebar scroll (if present)
    const list = document.getElementById(LIST_ID);
    if (list) list.addEventListener('scroll', closeOpenDropdown, { passive: true });
  }

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  ready(() => {
    wireKebabButtons();
    initObservers();
    initGlobalHandlers();
  });
})();
