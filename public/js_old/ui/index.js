// js/ui/index.js
// This file orchestrates the UI updates.

import * as render from './render.js';
import * as dom from './dom.js';

export * from './dom.js';
export * from './components.js';

/**
 * Main function to update the entire UI based on the user's authentication state.
 * @param {object|null} user - The user object or null if logged out.
 * @param {Array} profiles - The list of available profiles.
 * @param {string} selectedKey - The key of the currently active profile.
 */
export function updateUIForAuthState(user, profiles, selectedKey) {
    // This function no longer needs to pass handlers.
    // The render function will import them directly for reliability.
    render.renderSidebar(user, profiles, selectedKey);
}

