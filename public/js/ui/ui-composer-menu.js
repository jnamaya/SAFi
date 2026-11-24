let _isOpen = false;
let _openFlyout = null;
let _closeTimer = null;

const FLYOUT_CLOSE_DELAY = 220;
const MIN_VIEWPORT_GAP = 12;
const FLYOUT_MIN_HEIGHT = 176;
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

function _keepOnScreen(panel) {
    panel.classList.remove('flyout-left');
    panel.style.maxHeight = '';
    panel.style.overflowY = '';
    if (!DESKTOP.matches) return;

    const r = panel.getBoundingClientRect();
    if (r.right > window.innerWidth - 8) panel.classList.add('flyout-left');

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

export function closeComposerMenu() {
    _setFlyout(null);
    _isOpen = false;
    document.getElementById('composer-plus-menu')?.classList.add('hidden');
    _syncExpanded();
}

function _syncExpanded() {
    document.getElementById('composer-plus-btn')
        ?.setAttribute('aria-expanded', String(_isOpen));
}

export function updateAgentLabel(name) {
    const el = document.getElementById('plus-agent-current');
    if (el) el.textContent = name || 'None';
}

export function updateModelLabel(name) {
    const el = document.getElementById('plus-model-current');
    if (el) el.textContent = name || 'None';
}

export function updateDataSourcesLabel(connectedCount) {
    const el = document.getElementById('plus-data-current');
    if (!el) return;
    el.textContent = connectedCount > 0
        ? `${connectedCount} connected`
        : 'None connected';
}

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
