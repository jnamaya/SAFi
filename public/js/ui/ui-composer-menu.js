let _isOpen = false;
let _openFlyout = null;
let _closeTimer = null;

// Long enough to cross the gap between a row and its flyout on a diagonal —
// the classic cascading-menu problem. Closing on mouseleave with no grace
// period makes the submenu impossible to reach.
const FLYOUT_CLOSE_DELAY = 220;
// Breathing room against the top of the window, and a floor below which a
// scrolling list is more annoying than an overflowing one.
const MIN_VIEWPORT_GAP = 12;
const FLYOUT_MIN_HEIGHT = 160;
const DESKTOP = typeof window !== 'undefined'
    ? window.matchMedia('(min-width: 768px)') : { matches: false };

export function initComposerMenu({ onAttachFile }) {
    const plusBtn = document.getElementById('composer-plus-btn');
    const menu = document.getElementById('composer-plus-menu');
    if (!plusBtn || !menu) return;

    plusBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        _toggleMenu();
    });

    document.getElementById('plus-attach-btn')?.addEventListener('click', () => {
        closeComposerMenu();
        onAttachFile();
    });

    _initFlyouts();

    // Escape unwinds one level: an open flyout first, then the panel.
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape' || !_isOpen) return;
        if (_openFlyout) {
            _setFlyout(null);
            _openFlyout = null;
        } else {
            closeComposerMenu();
            plusBtn.focus();
        }
        e.stopPropagation();
    });

    document.addEventListener('click', (e) => {
        const plusContainer = document.getElementById('composer-plus-container');
        if (!plusContainer || !plusContainer.contains(e.target)) closeComposerMenu();
    });
}

/**
 * Category rows open a flyout: on hover for a mouse, on click for everything
 * (touch has no hover, and a tap that only "hovers" opens nothing).
 */
function _initFlyouts() {
    document.querySelectorAll('#composer-plus-menu [data-flyout]').forEach(wrap => {
        const trigger = wrap.querySelector('.submenu-trigger');
        if (!trigger) return;

        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            _setFlyout(_openFlyout === wrap ? null : wrap);
        });

        wrap.addEventListener('mouseenter', () => {
            if (!DESKTOP.matches) return;
            clearTimeout(_closeTimer);
            _setFlyout(wrap);
        });

        wrap.addEventListener('mouseleave', () => {
            if (!DESKTOP.matches) return;
            clearTimeout(_closeTimer);
            _closeTimer = setTimeout(() => _setFlyout(null), FLYOUT_CLOSE_DELAY);
        });
    });
}

/** Opens one flyout and closes the rest. Pass null to close them all. */
function _setFlyout(wrap) {
    clearTimeout(_closeTimer);
    document.querySelectorAll('#composer-plus-menu [data-flyout]').forEach(w => {
        const panel = w.querySelector('.submenu-panel');
        const trigger = w.querySelector('.submenu-trigger');
        const isOpen = w === wrap;
        panel?.classList.toggle('hidden', !isOpen);
        trigger?.setAttribute('aria-expanded', String(isOpen));
        if (isOpen && panel) _keepOnScreen(panel);
    });
    _openFlyout = wrap || null;
}

/**
 * Two corrections once a flyout is on screen.
 *
 * SIDE: it opens to the right by default; near the viewport edge that runs off
 * screen, so flip to the left. Desktop only — below md it is an inline
 * accordion with no side to flip to.
 *
 * HEIGHT: the flyout is anchored by its BOTTOM (md:bottom-0), so it grows
 * upward out of the row. That is the only direction with room: the panel hangs
 * above the composer, which is already at the bottom of the window, so a
 * downward flyout was guaranteed to run past the bottom edge and cut the list
 * off. Growing upward can still overshoot the top on a short window, so cap it
 * at the space actually above it.
 */
function _keepOnScreen(panel) {
    panel.classList.remove('flyout-left');
    panel.style.maxHeight = '';
    if (!DESKTOP.matches) return;

    const r = panel.getBoundingClientRect();
    if (r.right > window.innerWidth - 8) panel.classList.add('flyout-left');

    // r.bottom is fixed by the anchor, so everything above it is the room.
    const room = r.bottom - MIN_VIEWPORT_GAP;
    if (r.height > room) {
        panel.style.maxHeight = `${Math.max(FLYOUT_MIN_HEIGHT, room)}px`;
        panel.style.overflowY = 'auto';
    }
}

function _toggleMenu() {
    _isOpen = !_isOpen;
    document.getElementById('composer-plus-menu')?.classList.toggle('hidden', !_isOpen);
    _syncExpanded();
}

/**
 * Exported because the lists inside this panel are rendered by three other
 * modules, and choosing an item has to dismiss the panel that contains it.
 * They used to hide their own container, which no longer exists as a popover.
 */
export function closeComposerMenu() {
    _setFlyout(null);
    _isOpen = false;
    document.getElementById('composer-plus-menu')?.classList.add('hidden');
    _syncExpanded();
}

/** aria-expanded has to track the menu, not the click that opened it — the
 *  menu is closed from five places and a stale "true" tells a screen reader
 *  the opposite of what is on screen. */
function _syncExpanded() {
    document.getElementById('composer-plus-btn')
        ?.setAttribute('aria-expanded', String(_isOpen));
}

/**
 * The category rows show the current selection underneath their label.
 *
 * These were no-ops for exactly one commit, when every list was rendered
 * inline and its own check mark showed the selection — a subtitle then was a
 * second copy that could disagree. Flyouts changed that: the list is hidden
 * until you hover it, so the row is now the only way to see what is active
 * without opening anything.
 */
export function updateAgentLabel(name) {
    const el = document.getElementById('plus-agent-current');
    if (el) el.textContent = name || '—';
}

export function updateModelLabel(name) {
    const el = document.getElementById('plus-model-current');
    if (el) el.textContent = name || '—';
}

/** Connector count, so the row says something before it is opened. */
export function updateDataSourcesLabel(connectedCount) {
    const el = document.getElementById('plus-data-current');
    if (!el) return;
    el.textContent = connectedCount > 0
        ? `${connectedCount} connected`
        : 'None connected';
}

// AI disclosure (EU AI Act Art. 50(1)) below the composer. When the active
// agent is policy-governed, the generic sentence becomes a "this policy" link
// that opens the policy details modal; standalone/built-in agents keep the
// static fallback text baked into index.html.
export function updateAiDisclosure(profile, onViewPolicy) {
    const el = document.getElementById('ai-disclosure');
    if (!el) return;

    const hasPolicy = profile && profile.policy_id && profile.policy_id !== 'standalone';
    if (!hasPolicy || typeof onViewPolicy !== 'function') {
        el.textContent = "You are chatting with an AI agent. Responses are AI-generated and governed by your organization's policy.";
        return;
    }

    el.textContent = 'This AI agent is governed by ';
    const link = document.createElement('button');
    link.type = 'button';
    link.id = 'ai-disclosure-policy-link';
    link.className = 'underline underline-offset-2 hover:text-neutral-600 dark:hover:text-neutral-300 transition-colors';
    link.textContent = 'this policy';
    if (profile.policy_name) link.title = profile.policy_name;
    link.addEventListener('click', () => onViewPolicy(profile));
    el.appendChild(link);
    el.appendChild(document.createTextNode('.'));
}
