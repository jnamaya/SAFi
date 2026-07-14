let _isOpen = false;
let _openDropdown = null; // 'agent' | 'model' | 'data' | null

export function initComposerMenu({ onAttachFile, onToggleAgent, onToggleModel, onToggleData }) {
    const plusBtn = document.getElementById('composer-plus-btn');
    const menu = document.getElementById('composer-plus-menu');
    if (!plusBtn || !menu) return;

    plusBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        _closeAllDropdowns();
        _toggleMenu();
    });

    document.getElementById('plus-attach-btn')?.addEventListener('click', () => {
        _closeMenu();
        onAttachFile();
    });

    document.getElementById('plus-agent-btn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        _closeMenu();
        onToggleAgent();
    });

    document.getElementById('plus-model-btn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        _closeMenu();
        onToggleModel();
    });

    document.getElementById('composer-model-btn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        _closeMenu();
        onToggleModel();
    });

    document.getElementById('plus-data-btn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        _closeMenu();
        onToggleData();
    });

    document.addEventListener('click', (e) => {
        const plusContainer = document.getElementById('composer-plus-container');
        const modelContainer = document.getElementById('composer-model-container');
        const inPlus = plusContainer && plusContainer.contains(e.target);
        const inModel = modelContainer && modelContainer.contains(e.target);
        if (!inPlus && !inModel) {
            _closeMenu();
            _closeAllDropdowns();
        }
    });
}

function _toggleMenu() {
    _isOpen = !_isOpen;
    document.getElementById('composer-plus-menu')?.classList.toggle('hidden', !_isOpen);
}

function _closeMenu() {
    _isOpen = false;
    document.getElementById('composer-plus-menu')?.classList.add('hidden');
}

function _closeAllDropdowns() {
    ['agent-selector-dropdown', 'model-selector-dropdown', 'data-sources-dropdown'].forEach(id => {
        document.getElementById(id)?.classList.add('hidden');
    });
    _openDropdown = null;
}

export function toggleDropdown(id) {
    const el = document.getElementById(id);
    if (!el) return;
    const isHidden = el.classList.contains('hidden');

    _closeAllDropdowns();

    if (isHidden) {
        el.classList.remove('hidden');
        _openDropdown = id;
    }
}

export function updateAgentLabel(name, avatarUrl) {
    const menuEl = document.getElementById('plus-agent-current');
    if (menuEl) menuEl.textContent = name || '—';

    const nameEl = document.getElementById('composer-agent-name');
    if (nameEl) {
        nameEl.textContent = name || '';
        nameEl.title = name || '';
    }

    const avatarEl = document.getElementById('composer-agent-avatar');
    if (avatarEl) {
        if (avatarUrl) {
            avatarEl.src = avatarUrl;
            avatarEl.alt = name || '';
            avatarEl.classList.remove('hidden');
        } else {
            avatarEl.classList.add('hidden');
        }
    }
}

export function updateModelLabel(name) {
    const menuEl = document.getElementById('plus-model-current');
    if (menuEl) menuEl.textContent = name || '—';
    const barEl = document.getElementById('composer-model-label');
    if (barEl) barEl.textContent = name || '';
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

    el.textContent = 'You are chatting with an AI agent governed by ';
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
