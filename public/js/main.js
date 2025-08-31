// js/main.js
// The main entry point for the application.
// Its primary role is to initialize the app.

import { checkLoginStatus, attachEventListeners } from './events.js';

// Initializes the application when the DOM is fully loaded.
function initializeApp() {
    checkLoginStatus();
    attachEventListeners();
}

document.addEventListener('DOMContentLoaded', initializeApp);

