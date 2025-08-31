// js/state.js
// Manages the shared state of the application.

// Using an object to hold state makes it easy to add new state properties
// without changing function signatures across the app.
const appState = {
    currentConversationId: null,
    activeProfileData: {},
    availableProfiles: [],
    user: null,
};

export function getState() {
    return { ...appState };
}

export function setUser(user) {
    appState.user = user;
}

export function setCurrentConversationId(id) {
    appState.currentConversationId = id;
}

export function setActiveProfileData(data) {
    appState.activeProfileData = data;
}

export function setAvailableProfiles(profiles) {
    appState.availableProfiles = profiles;
}
