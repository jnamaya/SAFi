let _isOpen = false;

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

    // Escape closes the panel. There is no inner level to unwind any more —
    // the three lists are sections of this popover, not dropdowns that
    // replaced it.
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape' || !_isOpen) return;
        closeComposerMenu();
        e.stopPropagation();
        plusBtn.focus();
    });

    document.addEventListener('click', (e) => {
        const plusContainer = document.getElementById('composer-plus-container');
        if (!plusContainer || !plusContainer.contains(e.target)) closeComposerMenu();
    });
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
 * Kept as no-ops on purpose, with the reason, because both are called from
 * app.js on every profile/model change.
 *
 * The + menu used to show the current agent and model as subtitle rows under
 * "Switch Agent" / "Change AI Model". Those rows are gone: the lists are now
 * sections in the panel itself and mark their own selection with a check, so
 * a label repeating it was a second copy that could disagree. updateAgentLabel
 * also wrote to a composer pill (#composer-agent-name/#composer-agent-avatar)
 * that no longer exists in the markup at all.
 */
export function updateAgentLabel() { /* selection is shown by the list's check */ }

export function updateModelLabel() { /* selection is shown by the list's check */ }

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
