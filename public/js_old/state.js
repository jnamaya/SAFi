// js/state.js
// A simple module to hold and manage the application's state.

let appState = {
    user: null,
    currentConversationId: null,
    availableProfiles: [],
    activeProfile: {},
};

/**
 * Returns a copy of the current application state.
 * @returns {object} The current state.
 */
export function getState() {
    return { ...appState };
}

/**
 * Updates the application state by merging in new state.
 * @param {object} newState - An object with the state properties to update.
 */
export function setState(newState) {
    appState = { ...appState, ...newState };
}

