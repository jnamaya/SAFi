/**
 * js/ui/ui-data-sources.js
 * Manages the Data Sources dropdown menu in the chat composer.
 */

import * as api from '../core/api.js';

const BTN_ID = 'data-sources-btn';
const DROPDOWN_ID = 'data-sources-dropdown';

const ICONS = {
    google_drive: `<svg class="w-5 h-5 shrink-0" viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg"><path d="m6.6 66.85 3.85 6.65c.8 1.4 1.9 2.5 3.2 3.3l-13.65-23.7c0 0 6.6 13.75 6.6 13.75z" fill="#0066da"/><path d="m43.65 25-13.65-23.7c-2.85 0-5.4 1.5-6.8 4l-13.65 23.65 13.65 23.65z" fill="#00ac47"/><path d="m73.55 76.8c2.85 0 5.4-1.5 6.8-4l3.85-6.65-13.65-23.65-13.65 23.65-6.8-11.8h-27.3z" fill="#ea4335"/><path d="m43.65 25 13.65-23.65c-1.4-2.55-3.95-4.05-6.8-4.05h-27.25z" fill="#00832d"/><path d="m59.8 50.3-13.65-23.65-13.65-23.65-13.75 23.85 13.75 23.65z" fill="#2684fc"/><path d="m73.4 76.8h-27.3l-13.65-23.65h27.3l13.65 23.65c1.4-2.5 1.4-5.5 0-8.05z" fill="#ffba00"/></svg>`,
    sharepoint: `<svg class="w-5 h-5 shrink-0" viewBox="0 0 24 24" aria-hidden="true" fill="#036C70"><path d="M12.5 8c0-1.657-1.343-3-3-3s-3 1.343-3 3c0 1.657 1.343 3 3 3s3-1.343 3-3zM15 15.5c0-1.38-1.12-2.5-2.5-2.5S10 14.12 10 15.5s1.12 2.5 2.5 2.5 2.5-1.12 2.5-2.5zM7.5 15c0-1.11-.9-2-2-2s-2 .89-2 2 .9 2 2 2 2-.89 2-2zM19.5 7.5c0-1.38-1.12-2.5-2.5-2.5s-2.5 1.12-2.5 2.5 1.12 2.5 2.5 2.5 2.5-1.12 2.5-2.5z"/></svg>`
};

let isDropdownOpen = false;

/**
 * Initializes the Data Sources dropdown interactions.
 * Call this from app.js after DOM load.
 */
export function initDataSources() {
    const btn = document.getElementById(BTN_ID);
    const dropdown = document.getElementById(DROPDOWN_ID);

    if (!btn || !dropdown) return;

    // Toggle Dropdown
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleDropdown();
    });

    // Close when clicking outside
    document.addEventListener('click', (e) => {
        if (isDropdownOpen && !dropdown.contains(e.target) && !btn.contains(e.target)) {
            closeDropdown();
        }
    });

    // Initial check
    checkDataSources();
}

function toggleDropdown() {
    isDropdownOpen = !isDropdownOpen;
    const dropdown = document.getElementById(DROPDOWN_ID);
    if (isDropdownOpen) {
        dropdown.classList.remove('hidden');
    } else {
        dropdown.classList.add('hidden');
    }
}

function closeDropdown() {
    isDropdownOpen = false;
    document.getElementById(DROPDOWN_ID)?.classList.add('hidden');
}

/**
 * Fetches status and updates the menu items.
 */
export async function checkDataSources() {
    try {
        const response = await api.fetchAuthStatus();
        const connected = (response && response.connected) ? response.connected : [];
        renderMenu(connected);
    } catch (e) {
        console.warn('Failed to fetch data source status', e);
        renderMenu([]);
    }
}

function renderMenu(connectedList) {
    const dropdown = document.getElementById(DROPDOWN_ID);
    if (!dropdown) return;

    dropdown.innerHTML = '';

    const sources = [
        {
            id: 'google',
            icon: ICONS.google_drive,
            title: 'Google Drive',
            authUrl: '/api/auth/google/login'
        },
        {
            id: 'microsoft',
            icon: ICONS.sharepoint,
            title: 'OneDrive / SharePoint',
            authUrl: '/api/auth/microsoft/login'
        }
    ];

    sources.forEach(source => {
        const isConnected = connectedList.includes(source.id);

        const item = document.createElement('a');
        // If connected, no-op (or maybe disconnect later). If not, link to auth.
        item.href = isConnected ? '#' : source.authUrl;

        item.className = `
            flex items-center gap-3 px-3 py-2 rounded-lg transition-colors group
            ${isConnected
                ? 'hover:bg-neutral-100 dark:hover:bg-neutral-800 cursor-default'
                : 'hover:bg-green-50 dark:hover:bg-green-900/20'
            }
        `;

        // Inner HTML: Icon + Text + Status
        item.innerHTML = `
            ${source.icon}
            <div class="flex flex-col">
                <span class="text-sm font-medium text-neutral-900 dark:text-neutral-100">${source.title}</span>
                <span class="text-xs ${isConnected ? 'text-green-600 dark:text-green-400' : 'text-neutral-500 group-hover:text-green-600 dark:group-hover:text-green-400'}">
                    ${isConnected ? '● Connected' : 'Click to connect'}
                </span>
            </div>
        `;

        if (isConnected) {
            item.addEventListener('click', (e) => e.preventDefault());
        }

        dropdown.appendChild(item);
    });
}
