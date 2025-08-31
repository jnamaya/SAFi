// js/ui/index.js
// A central hub for importing and exporting all UI-related functions.
// This makes it easy to import UI functionality from a single place.

import * as dom from './dom.js';
import * as render from './render.js';
import * as components from './components.js';

export const ui = {
    ...dom,
    ...render,
    ...components,
};

export function updateUIForAuthState(user, profiles, selectedKey) {
    const loginView = ui.elements.loginView();
    const chatView = ui.elements.chatView();
    const sidebarContainer = ui.elements.sidebarContainer();
    if (!loginView || !chatView || !sidebarContainer) return;

    if (user) {
        loginView.classList.add('hidden');
        chatView.classList.remove('hidden');
        ui.renderAuthenticatedUI(user, profiles, selectedKey);
    } else {
        sidebarContainer.innerHTML = '';
        loginView.classList.remove('hidden');
        chatView.classList.add('hidden');
    }
}
