import { formatTime, formatRelativeTime } from './utils.js';
import * as ui from './ui.js'; // For access to elements and showToast
import * as api from './api.js'; // Import API for TTS call

// --- GLOBAL STATE FOR AUDIO ---
let audio = null;
let currentPlaybackElement = null; // Stores the button element currently playing

// --- ICON TEMPLATES ---
// Play icon (Audio waves)
const iconPlay = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.536 8.464a4.5 4.5 0 010 7.072m2.478-9.431a7.5 7.5 0 010 12.382m-13.04-12.382a7.5 7.5 0 010 12.382m2.478-9.431a4.5 4.5 0 010 7.072M5.5 12h-.01"></path></svg>`;
// Pause icon (Two vertical lines)
const iconPause = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10a1 1 0 011 1v4a1 1 0 01-1 1h-2a1 1 0 01-1-1v-4a1 1 0 011-1h2zM9 10a1 1 0 011 1v4a1 1 0 01-1 1H7a1 1 0 01-1-1v-4a1 1 0 011-1h2z"></path></svg>`;
const iconLoading = `<div class="spinner-border w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"></div>`;

// --- TTS HELPER FUNCTION ---
async function playSpeech(text, buttonElement) {
    // Case A: A different message's audio is currently active (playing or paused). Stop and reset it.
    if (currentPlaybackElement && currentPlaybackElement !== buttonElement) {
        resetAudioState();
    }
    
    // Set the button element for the current interaction
    currentPlaybackElement = buttonElement;

    // Case 1: Audio exists AND is playing -> PAUSE
    if (audio && !audio.paused) {
        audio.pause();
        buttonElement.innerHTML = iconPlay; // Change icon to Play (Ready to Resume)
        buttonElement.classList.remove('text-green-500', 'animate-pulse');
        return;
    }
    
    // Case 2: Audio exists AND is paused -> RESUME
    if (audio && audio.paused) {
        audio.play().catch(e => {
            console.error("Audio playback failed (resume):", e);
            ui.showToast('Audio playback blocked by browser.', 'error');
            resetAudioState();
        });
        buttonElement.innerHTML = iconPause; // Change icon to Pause (Currently Playing)
        buttonElement.classList.add('text-green-500');
        return;
    }

    // Case 3: No audio loaded yet -> FETCH AND PLAY
    
    // Set loading state
    buttonElement.innerHTML = iconLoading;
    buttonElement.classList.add('text-green-500', 'animate-pulse');

    try {
        ui.showToast('Generating audio...', 'info', 1500);
        const audioBlob = await api.fetchTTSAudio(text);
        
        // Clear any old audio object reference
        if (audio) {
             URL.revokeObjectURL(audio.src);
        }
        
        const audioUrl = URL.createObjectURL(audioBlob);
        audio = new Audio(audioUrl);
        
        audio.oncanplaythrough = () => {
            // Start playback
            audio.play().catch(e => {
                console.error("Audio playback failed (initial):", e);
                ui.showToast('Audio playback blocked by browser.', 'error');
                resetAudioState();
            });
            // Update button to Pause icon
            currentPlaybackElement.innerHTML = iconPause; 
            currentPlaybackElement.classList.remove('animate-pulse');
            currentPlaybackElement.classList.add('text-green-500');
        };

        audio.onended = () => {
            // Audio finished playing
            resetAudioState();
        };

        audio.onerror = (e) => {
            console.error("Audio error:", e);
            ui.showToast('Error playing audio.', 'error');
            resetAudioState();
        };

    } catch (error) {
        console.error('TTS generation failed:', error);
        ui.showToast('TTS service unavailable.', 'error');
        resetAudioState();
    }
}

function resetAudioState() {
    if (audio) {
        audio.pause();
        URL.revokeObjectURL(audio.src);
        audio = null;
    }
    if (currentPlaybackElement) {
        // Reset the button to 'Play' icon
        currentPlaybackElement.innerHTML = iconPlay;
        currentPlaybackElement.classList.remove('text-green-500', 'animate-pulse');
        currentPlaybackElement = null;
    }
}

// --- MARKDOWN & HIGHLIGHTING SETUP ---

marked.setOptions({
  breaks: false, 
  gfm: true,
  mangle: false,
  headerIds: false,
  highlight: function(code, lang) {
    const language = hljs.getLanguage(lang) ? lang : 'plaintext';
    return hljs.highlight(code, { language }).value;
  }
});

// --- AVATAR HELPERS ---

/**
 * Maps a profile name to a static avatar image path.
 * @param {string | null} profileName 
 * @returns {string} The path to the avatar image
 */
function getAvatarForProfile(profileName) {
  // Normalize the profile name to lowercase, trimmed, and replace underscores with spaces for common matching
  let cleanName = profileName ? profileName.trim().toLowerCase() : null;

  // Check for common internal key format (e.g., 'health_navigator')
  if (cleanName && cleanName.includes('_')) {
    // If it's the internal key, use the key itself for matching
    // and also try the space-separated version for robustness
    if (cleanName === 'health_navigator') {
        return 'assets/health_navigator.svg';
    }
    // Fall through to switch after primary check
  }
  
  // Standard switch matching the display name (e.g., "The Health Navigator" -> "the health navigator")
  switch (cleanName) {
    case 'the philosopher':
      return 'assets/philosopher.svg';
    case 'the fiduciary':
      return 'assets/fiduciary.svg';
    case 'the health navigator':
    case 'health navigator': // Handles if "the" is missing in the display name
      return 'assets/health_navigator.svg'; // Correct path to file
    case 'the jurist':
      return 'assets/jurist.svg';
    case 'the bible scholar':
      return 'assets/bible_scholar.svg';
    case 'the safi guide':
    default:
      return 'assets/safi.svg';
  }
}

// --- GLOBAL UI RENDERING ---

export function updateUIForAuthState(user, logoutHandler, deleteAccountHandler, themeHandler) {
  ui._ensureElements();
  if (user) {
    ui.elements.loginView.classList.add('hidden');
    ui.elements.chatView.classList.remove('hidden');
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');

    const pic = user.picture || user.avatar || `https://placehold.co/40x40/7e22ce/FFFFFF?text=${user.name ? user.name.charAt(0) : 'U'}`;
    const name = user.name || user.email || 'User';
    
    ui.elements.sidebarContainer.innerHTML = `
        <div id="sidebar-overlay" class="fixed inset-0 bg-black/50 z-30 hidden md:hidden"></div>
        <aside id="sidebar" class="fixed inset-y-0 left-0 w-80 bg-neutral-100 dark:bg-neutral-900 text-neutral-900 dark:text-white flex flex-col z-40 transform -translate-x-full transition-transform duration-300 ease-in-out md:translate-x-0 h-full border-r border-gray-200 dark:border-gray-800">
          <div class="p-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between shrink-0">
            <div class="flex items-center gap-3">
              <div class="app-logo h-10 w-10">
                <img src="assets/logo.png" alt="SAFi Logo" class="rounded-lg w-full h-full" onerror="this.onerror=null; this.src='https://placehold.co/40x40/22c55e/FFFFFF?text=S'">
              </div>
              <div>
                <h1 class="text-lg font-bold">SAFi</h1>
                <p class="text-xs text-gray-500 dark:text-gray-400">The Governance Engine For AI</p>
              </div>
            </div>
            <button id="close-sidebar-button" type="button" aria-label="Close sidebar" class="p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 md:hidden">
              <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>
          
          <div class="p-4 shrink-0">
            <button id="new-chat-button" type="button" class="w-full bg-green-600 text-white font-semibold px-4 py-2.5 rounded-lg hover:bg-green-700 transition-colors flex items-center justify-center gap-2 shadow-sm hover:shadow-md">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path></svg>
              New Chat
            </button>
          </div>
           
          <nav id="convo-list" aria-label="Conversation history" class="flex-1 overflow-y-auto p-2 space-y-0.5 custom-scrollbar min-h-0">
            <h3 class="px-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">Conversations</h3>
          </nav>
          
          <div id="user-profile-container" class="p-4 border-t border-gray-200 dark:border-gray-800 shrink-0">
            <div class="flex items-center justify-between gap-3 min-w-0">
              
              <div class="flex items-center gap-3 min-w-0 flex-1">
                <img src="${pic}" alt="User Avatar" class="w-10 h-10 rounded-full">
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-semibold truncate">${name}</p>
                  <p class="text-xs text-neutral-500 dark:text-neutral-400 truncate">${user.email}</p>
                </div>
              </div>

              <button id="control-panel-btn" type="button" class="shrink-0 p-2 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors" aria-label="Open Control Panel">
                <svg class="w-6 h-6 text-neutral-600 dark:text-neutral-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924-1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0 3.35a1.724 1.724 0 001.066 2.573c-.94-1.543.826 3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
              </button>
            </div>
          </div>
        </aside>
    `;
  } else {
    ui.elements.sidebarContainer.innerHTML = '';
    ui.elements.loginView.classList.remove('hidden');
    ui.elements.chatView.classList.add('hidden');
    if (ui.elements.controlPanelView) ui.elements.controlPanelView.classList.add('hidden');
  }
}

// --- MESSAGE RENDERING ---

let lastRenderedDay = '';

function maybeInsertDayDivider(date) {
  ui._ensureElements();
  const key = date.toLocaleDateString();
  if (key !== lastRenderedDay) {
    lastRenderedDay = key;
    const div = document.createElement('div');
    div.className = 'flex items-center justify-center my-2';
    div.innerHTML = `<div class="text-xs text-neutral-500 dark:text-neutral-400 px-3 py-1 rounded-full bg-neutral-100 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700">${date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}</div>`;
    ui.elements.chatWindow.appendChild(div);
  }
}

export function displaySimpleGreeting(firstName) {
  ui._ensureElements();
  const existingGreeting = ui.elements.chatWindow.querySelector('.simple-greeting');
  if (existingGreeting) existingGreeting.remove();

  const greetingDiv = document.createElement('div');
  greetingDiv.className = 'simple-greeting text-4xl font-bold text-center py-8 text-neutral-800 dark:text-neutral-200';
  greetingDiv.textContent = `Hi ${firstName}`;
  ui.elements.chatWindow.appendChild(greetingDiv);
}

export function displayMessage(sender, text, date = new Date(), messageId = null, payload = null, whyHandler = null, options = {}) {
  ui._ensureElements();
  const emptyState = ui.elements.chatWindow.querySelector('.empty-state-container');
  if (emptyState) emptyState.remove();
  const simpleGreeting = ui.elements.chatWindow.querySelector('.simple-greeting');
  if (simpleGreeting) simpleGreeting.remove();

  maybeInsertDayDivider(date);

  const messageContainer = document.createElement('div');
  messageContainer.className = 'message-container';
  if (messageId) {
    messageContainer.dataset.messageId = messageId;
  }
  
  const suggestedPrompts = options.suggestedPrompts || [];

  const messageDiv = document.createElement('div');
  messageDiv.className = `message ${sender}`;

  // This variable will hold the TTS button if needed.
  let ttsButtonElement = null; 
  const final_text = String(text ?? ''); // Capture raw text for TTS

  if (sender === 'ai') {
    const profileName = (payload && payload.profile) ? payload.profile : null;
    const avatarUrl = getAvatarForProfile(profileName);
    
    let promptsHtml = '';
    if (suggestedPrompts.length > 0) {
        const promptsList = suggestedPrompts.map(p => 
            `<button class="ai-prompt-suggestion-btn text-left w-full p-3 rounded-lg bg-neutral-100 dark:bg-neutral-800 hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors border border-neutral-200 dark:border-neutral-700 text-sm italic">
                "${p}"
            </button>`
        ).join('');
        
        promptsHtml = `
            <div class="mt-3 pt-3 border-t border-neutral-200 dark:border-neutral-700 space-y-2 prompt-suggestions-container">
                <p class="text-xs font-semibold text-neutral-500 dark:text-neutral-400 uppercase tracking-wider mb-1">Try a different prompt:</p>
                ${promptsList}
            </div>
        `;
    }

    // --- NEW: TTS Button Creation ---
    ttsButtonElement = document.createElement('button'); // Define the variable here
    ttsButtonElement.className = 'tts-btn flex items-center justify-center p-1 rounded-full hover:bg-neutral-200 dark:hover:bg-neutral-700 transition-colors shrink-0';
    ttsButtonElement.setAttribute('aria-label', 'Play message audio');
    // Initial speaker icon (waves)
    ttsButtonElement.innerHTML = iconPlay; // Use the defined iconPlay constant
    
    ttsButtonElement.addEventListener('click', () => {
        playSpeech(final_text, ttsButtonElement); 
    });
    // --- END NEW ---

    messageDiv.innerHTML = `
      <div class="ai-avatar">
        <img src="${avatarUrl}" alt="${profileName || 'SAFi'} Avatar" class="w-full h-full rounded-lg">
      </div>
      <div class="ai-content-wrapper">
        <div class="chat-bubble">
          <!-- Content will be injected here -->
          <div class="meta"></div>
        </div>
        ${promptsHtml}
      </div>
    `;
    const bubble = messageDiv.querySelector('.chat-bubble');
    bubble.insertAdjacentHTML('afterbegin', DOMPurify.sanitize(marked.parse(final_text)));
    
  } else {
    const bubbleHtml = DOMPurify.sanitize(marked.parse(final_text));
    const avatarUrl = options.avatarUrl || `https://placehold.co/40x40/7e22ce/FFFFFF?text=U`;
    messageDiv.innerHTML = `
        <div class="user-content-wrapper">
           <div class="chat-bubble">
             ${bubbleHtml}
             <div class="meta"></div>
           </div>
        </div>
        <div class="user-avatar">
            <img src="${avatarUrl}" alt="User Avatar" class="w-full h-full rounded-full">
        </div>
    `;
  }
  
  const metaDiv = messageDiv.querySelector('.meta');
  const leftMeta = document.createElement('div');
  const rightMeta = document.createElement('div');
  
  // --- MODIFIED: Align items-center for a cleaner timestamp row ---
  rightMeta.className = 'flex items-center gap-2 ml-auto';

  const hasLedger = payload && Array.isArray(payload.ledger) && payload.ledger.length > 0;
  if (hasLedger && whyHandler) {
      const whyButton = document.createElement('button');
      whyButton.className = 'why-btn';
      whyButton.textContent = 'View Ethical Reasoning';
      whyButton.addEventListener('click', () => whyHandler(payload));
      leftMeta.appendChild(whyButton);
  }
  
  metaDiv.appendChild(leftMeta);

  const stampDiv = document.createElement('div');
  stampDiv.className = 'stamp text-xs'; // Ensure text size is small
  stampDiv.textContent = formatTime(date);
  
  // --- MODIFIED: Prepend TTS button to rightMeta (before stampDiv) for AI messages ---
  if (sender === 'ai' && ttsButtonElement) {
      rightMeta.prepend(ttsButtonElement);
  }
  // --- END MODIFIED ---

  rightMeta.appendChild(stampDiv);
  metaDiv.appendChild(rightMeta);
  
  messageContainer.appendChild(messageDiv);

  ui.elements.chatWindow.appendChild(messageContainer);
  ui.scrollToBottom();
  
  messageContainer.querySelectorAll('.ai-prompt-suggestion-btn').forEach(btn => {
      btn.addEventListener('click', () => {
          const promptText = btn.textContent.replace(/"/g, '').trim();
          ui.elements.messageInput.value = promptText;
          ui.elements.sendButton.disabled = false;
          ui.elements.messageInput.style.height = 'auto'; 
          ui.elements.messageInput.style.height = `${ui.elements.messageInput.scrollHeight}px`; 
          ui.elements.messageInput.focus();
          ui.elements.sendButton.click();
          const suggestionBox = btn.closest('.prompt-suggestions-container');
          if (suggestionBox) {
              suggestionBox.remove();
          }
      });
  });
  
  return messageContainer;
}

export function updateMessageWithAudit(messageId, payload, whyHandler) {
    ui._ensureElements();
    const messageContainer = document.querySelector(`[data-message-id="${messageId}"]`);
    if (!messageContainer) return;

    const hasLedger = payload && Array.isArray(payload.ledger) && payload.ledger.length > 0;
    if (!hasLedger) return;

    const metaDiv = messageContainer.querySelector('.meta');
    if (metaDiv && !metaDiv.querySelector('.why-btn')) {
        const whyButton = document.createElement('button');
        whyButton.className = 'why-btn';
        whyButton.textContent = 'View Ethical Reasoning';
        whyButton.addEventListener('click', () => whyHandler(payload));
        
        const leftMeta = metaDiv.querySelector('div:first-child');
        if (leftMeta) {
            // Find TTS button in the rightMeta container (which now holds the date and TTS button)
            const rightMeta = metaDiv.querySelector('div:last-child');

            // Find an existing button to maintain order if possible
            const existingButton = leftMeta.querySelector('button');

            if (existingButton) {
                leftMeta.insertBefore(whyButton, existingButton);
            } else {
                 leftMeta.appendChild(whyButton);
            }
        } else {
            const newLeftMeta = document.createElement('div');
            newLeftMeta.appendChild(whyButton);
            metaDiv.insertBefore(newLeftMeta, metaDiv.firstChild);
        }
    }
}

export function showLoadingIndicator(profileName) {
  ui._ensureElements();
  ui.clearLoadingInterval(); 

  const emptyState = ui.elements.chatWindow.querySelector('.empty-state-container');
  if (emptyState) emptyState.remove();
  const simpleGreeting = ui.elements.chatWindow.querySelector('.simple-greeting');
  if (simpleGreeting) simpleGreeting.remove();
  
  maybeInsertDayDivider(new Date());

  const loadingContainer = document.createElement('div');
  loadingContainer.className = 'message-container';
  
  const avatarUrl = getAvatarForProfile(profileName || null); 
  const altText = (profileName || 'SAFi') + ' Avatar';

  loadingContainer.innerHTML = `
    <div class="message ai">
        <div class="ai-avatar">
            <img src="${avatarUrl}" alt="${altText}" class="w-full h-full rounded-lg">
        </div>
        <div class="ai-content-wrapper">
            <div class="flex items-center gap-3">
              <div class="thinking-spinner"></div>
              <span id="thinking-status" class="text-gray-500 dark:text-gray-400 italic">Thinking...</span>
            </div>
        </div>
    </div>`;
  ui.elements.chatWindow.appendChild(loadingContainer);
  ui.scrollToBottom();

  const statusSpan = loadingContainer.querySelector('#thinking-status');

  const stage1IntellectMessages = [
    "Consulting with the Intellect...",
    "Packaging the prompt for the AI model...",
    "Drafting response..."
  ];
  
  const stage2WillMessages = [
    "Intellect draft received. Consulting Will faculty...",
    "Analyzing draft against non-negotiable rules...",
    "Running gatekeeper check..."
  ];

  const stage3DelayedMessages = [
    "This is a complex prompt, so generation is taking longer than usual...",
    "If you are using claude,Gemini or GTP for the Intellect, those models take longer, sorry..",
    "Ensuring a high-quality draft, please wait...",
    "Almost done hang on...",
    "Just a few more moments..."
  ];

  let stage = 0;

  const updateStatus = () => {
    stage++;
    let messagePool;

    if (stage === 1) {
      messagePool = stage1IntellectMessages;
    } else if (stage === 2) {
      messagePool = stage2WillMessages;
    } else {
      messagePool = stage3DelayedMessages;
    }
    
    const message = messagePool[Math.floor(Math.random() * messagePool.length)];
    if (statusSpan) {
      statusSpan.textContent = message;
    }
  };

  updateStatus();

  const randomDelay = 3000 + (Math.random() * 1500);
  const interval = setInterval(updateStatus, randomDelay);
  ui.setLoadingInterval(interval); // Save interval in ui.js

  return loadingContainer;
}

// --- CONVERSATION LINK RENDERING ---

function createDropdownMenu(convoId, handlers) {
  const menu = document.createElement('div');
  menu.className = 'convo-menu-dropdown fixed z-50 w-36 bg-white dark:bg-neutral-800 rounded-lg shadow-xl border border-neutral-200 dark:border-neutral-700 p-1';
  menu.dataset.menuId = convoId;
  
  const renameButton = document.createElement('button');
  renameButton.className = "flex items-center gap-3 w-full text-left px-3 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-md";
  renameButton.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.5L15.232 5.232z"></path></svg>
    <span>Rename</span>
  `;
  renameButton.addEventListener('click', (e) => {
    e.stopPropagation();
    ui.closeAllConvoMenus();
    handlers.renameHandler(convoId, document.querySelector(`a[data-id="${convoId}"] .convo-title`).textContent);
  });
  
  const deleteButton = document.createElement('button');
  deleteButton.className = "flex items-center gap-3 w-full text-left px-3 py-2 text-sm text-red-600 dark:text-red-500 hover:bg-neutral-100 dark:hover:bg-neutral-700 rounded-md";
  deleteButton.innerHTML = `
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-4v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
    <span>Delete</span>
  `;
  deleteButton.addEventListener('click', (e) => {
    e.stopPropagation();
    ui.closeAllConvoMenus();
    handlers.deleteHandler(convoId);
  });

  menu.appendChild(renameButton);
  menu.appendChild(deleteButton);
  menu.addEventListener('click', (e) => e.stopPropagation());

  return menu;
}

function positionDropdown(menu, button) {
  const rect = button.getBoundingClientRect();
  menu.style.top = 'auto';
  menu.style.bottom = `${window.innerHeight - rect.top + 4}px`;
  menu.style.left = 'auto';
  menu.style.right = `${window.innerWidth - rect.right}px`; 
}

export function prependConversationLink(convo, handlers) {
  ui._ensureElements();
  const convoList = document.getElementById('convo-list');
  if (!convoList) return;

  const link = renderConversationLink(convo, handlers);
  const listHeading = convoList.querySelector('h3');
  
  if (listHeading) {
    listHeading.after(link); 
  } else {
    convoList.prepend(link); 
  }
}

export function renderConversationLink(convo, handlers) {
  ui._ensureElements();
  const { switchHandler, renameHandler, deleteHandler } = handlers;
  const link = document.createElement('a');
  link.href = '#';
  link.dataset.id = convo.id;
  
  link.className = 'group relative flex items-start justify-between px-3 py-2 hover:bg-neutral-200 dark:hover:bg-neutral-800 rounded-lg transition-colors duration-150';
  
  link.innerHTML = `
    <div class="flex-1 min-w-0 pr-8">
        <span class="convo-title truncate block text-sm font-medium">${convo.title || 'Untitled'}</span>
        <span class="convo-timestamp truncate block text-xs text-neutral-500 dark:text-neutral-400">
            ${convo.last_updated ? formatRelativeTime(convo.last_updated) : ''}
        </span>
    </div>
    <button data-action="menu" class="convo-menu-button opacity-0 group-hover:opacity-100 focus:opacity-100 
                   absolute right-2 top-1/2 -translate-y-1/2 
                   p-1.5 rounded-full hover:bg-neutral-300 dark:hover:bg-neutral-700" 
            aria-label="Conversation options">
       <svg class="w-5 h-5 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z"></path></svg>
    </button>
  `;
  
  let longPressTimer = null;
  let isLongPress = false;
  const longPressDuration = 500; 

  const handleTouchStart = (e) => {
    isLongPress = false;
    longPressTimer = setTimeout(() => {
      isLongPress = true;
      const actionButton = link.querySelector('button[data-action="menu"]');
      if (!actionButton) return;
      e.preventDefault(); 
      e.stopPropagation();
      if (window.navigator && window.navigator.vibrate) {
        window.navigator.vibrate(50);
      }
      if (document.querySelector('.convo-menu-dropdown')) {
        ui.closeAllConvoMenus();
        return;
      }
      const menu = createDropdownMenu(convo.id, handlers);
      positionDropdown(menu, actionButton);
      ui.setOpenDropdown(menu);
    }, longPressDuration);
  };

  const handleTouchEnd = (e) => {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }
    if (isLongPress) {
      e.preventDefault();
      e.stopPropagation();
    }
  };

  const handleTouchMove = () => {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }
  };

  link.addEventListener('touchstart', handleTouchStart, { passive: false });
  link.addEventListener('touchend', handleTouchEnd);
  link.addEventListener('touchcancel', handleTouchMove);
  link.addEventListener('touchmove', handleTouchMove);

  link.addEventListener('contextmenu', (e) => {
      e.preventDefault();
  });
  
  link.addEventListener('click', (e) => {
    if (isLongPress) {
        e.preventDefault();
        e.stopPropagation();
        return;
    }

    const actionButton = e.target.closest('button[data-action="menu"]');

    if (actionButton) {
      e.preventDefault();
      e.stopPropagation();
      
      if (document.querySelector('.convo-menu-dropdown')) {
        ui.closeAllConvoMenus();
        return;
      }

      const menu = createDropdownMenu(convo.id, handlers);
      positionDropdown(menu, actionButton);
      ui.setOpenDropdown(menu);
      
    } else {
      e.preventDefault();
      ui.closeAllConvoMenus();
      if (window.innerWidth < 768) ui.closeSidebar();
      switchHandler(convo.id);
    }
  });
  return link;
}

export function resetChatView() {
  ui._ensureElements();
  lastRenderedDay = '';
  while (ui.elements.chatWindow.firstChild) {
    ui.elements.chatWindow.removeChild(ui.elements.chatWindow.firstChild);
  }
}

export function setActiveConvoLink(id) {
  ui._ensureElements();
  document.querySelectorAll('#convo-list > a').forEach(link => {
    const isActive = link.dataset.id === String(id);
    const title = link.querySelector('.convo-title');
    const timestamp = link.querySelector('.convo-timestamp');

    link.classList.toggle('bg-green-600', isActive);
    link.classList.toggle('text-white', isActive);
    link.classList.toggle('dark:bg-green-600', isActive);
    link.classList.toggle('dark:text-white', isActive);
    link.classList.toggle('text-neutral-900', !isActive);
    link.classList.toggle('dark:text-white', !isActive);
    link.classList.toggle('hover:bg-neutral-200', !isActive);
    link.classList.toggle('dark:hover:bg-neutral-800', !isActive);
    
    title?.classList.toggle('font-semibold', isActive);
    title?.classList.toggle('font-medium', !isActive);

    if (timestamp) {
      timestamp.classList.toggle('text-green-100', isActive);
      timestamp.classList.toggle('dark:text-green-100', isActive);
      
      timestamp.classList.toggle('text-neutral-500', !isActive);
      timestamp.classList.toggle('dark:text-neutral-400', !isActive);
    }
  });
}

export function updateChatTitle(title) {
  const mobileTitle = document.getElementById('chat-title');
  const desktopTitle = document.getElementById('chat-title-desktop');
  const newTitle = title || 'SAFi';

  if (mobileTitle) {
    mobileTitle.textContent = newTitle;
  }
  if (desktopTitle) {
    desktopTitle.textContent = newTitle;
  }
}

export function updateActiveProfileChip(profileName) {
  ui._ensureElements();
  
  const avatarUrl = getAvatarForProfile(profileName);
  const textLabel = "Persona:";
  const profileNameText = profileName || 'Default';

  if (ui.elements.activeProfileChip) {
    ui.elements.activeProfileChip.classList.add('flex', 'items-center', 'gap-2');
    ui.elements.activeProfileChip.innerHTML = `
      <span class="truncate flex-shrink-0">${textLabel}</span>
      <img src="${avatarUrl}" alt="${profileName || 'SAFi'} Avatar" class="w-5 h-5 rounded-md flex-shrink-0">
      <span class="truncate">${profileNameText}</span>
    `;
  }
  if (ui.elements.activeProfileChipMobile) {
    ui.elements.activeProfileChipMobile.classList.add('flex', 'items-center', 'gap-2', 'mx-auto');
    ui.elements.activeProfileChipMobile.innerHTML = `
      <span class="font-semibold truncate flex-shrink-0">${textLabel}</span>
      <img src="${avatarUrl}" alt="${profileName || 'SAFi'} Avatar" class="w-6 h-6 rounded-lg flex-shrink-0">
      <span class="font-semibold truncate">${profileNameText}</span>
    `;
  }
}

export function displayEmptyState(activeProfile, promptClickHandler) {
  ui._ensureElements();
  const existingEmptyState = document.querySelector('.empty-state-container');
  if (existingEmptyState) {
    existingEmptyState.remove();
  }

  if (activeProfile && ui.elements.chatWindow) {
    const valuesHtml = (activeProfile.values || []).map(v => `<span class="value-chip">${v.value}</span>`).join(' ');
    const promptsHtml = (activeProfile.example_prompts || []).map(p => `<button class="example-prompt-btn">"${p}"</button>`).join('');
    
    // Use description_short if available, fallback to description, then empty
    const description = activeProfile.description_short || activeProfile.description || '';
    const descriptionHtml = description
      ? `<p class="text-base text-neutral-600 dark:text-neutral-300 mt-4 max-w-2xl mx-auto">${description}</p>`
      : '';
    
    const avatarUrl = getAvatarForProfile(activeProfile.name);

    const emptyStateContainer = document.createElement('div');
    emptyStateContainer.className = 'empty-state-container';
    emptyStateContainer.innerHTML = `<div class="text-center pt-8">
        <p class="text-lg text-neutral-500 dark:text-neutral-400">SAFi is currently set with the</p>
        <h2 class="text-2xl font-semibold my-2">${activeProfile.name || 'Default'}</h2>
        <img src="${avatarUrl}" alt="${activeProfile.name || 'SAFi'} Avatar" class="w-20 h-20 rounded-lg mx-auto mt-4">
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-4">persona, which includes these values:</p>
        <div class="flex flex-wrap justify-center gap-2 my-4 max-w-2xl mx-auto">${valuesHtml}</div>
        ${descriptionHtml}
         <div class="mt-6 text-sm text-neutral-700 dark:text-neutral-300">
            To choose a different persona, open the <svg class="inline-block w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924-1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0 3.35a1.724 1.724 0 001.066 2.573c-.94-1.543.826 3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg> 'Control Panel'.
        </div>
        <p class="text-sm text-neutral-500 dark:text-neutral-400 mt-6 mb-3">To begin, type below or pick an example prompt:</p>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 max-w-6xl mx-auto">${promptsHtml}</div>
      </div>`;
    
    ui.elements.chatWindow.appendChild(emptyStateContainer);

    emptyStateContainer.querySelectorAll('.example-prompt-btn').forEach(btn => {
        btn.addEventListener('click', () => promptClickHandler(btn.textContent.replace(/"/g, '')));
    });
  }
}

// --- SETTINGS RENDERING (CONTROL PANEL) ---

export function setupControlPanelTabs() {
    ui._ensureElements();
    const tabs = [ui.elements.cpNavProfile, ui.elements.cpNavModels, ui.elements.cpNavDashboard, ui.elements.cpNavAppSettings];
    const panels = [ui.elements.cpTabProfile, ui.elements.cpTabModels, ui.elements.cpTabDashboard, ui.elements.cpTabAppSettings];
    
    tabs.forEach((tab, index) => {
        if (!tab) return;
        tab.addEventListener('click', () => {
            tabs.forEach(t => t?.classList.remove('active'));
            tab.classList.add('active');
            
            panels.forEach(p => p?.classList.add('hidden'));
            if (panels[index]) {
                panels[index].classList.remove('hidden');
            }

            if (tab === ui.elements.cpNavDashboard) {
                renderSettingsDashboardTab();
            }
        });
    });
    
    if (tabs[0]) {
      tabs[0].click();
    }
}

export function renderSettingsProfileTab(profiles, activeProfileKey, onProfileChange) {
  ui._ensureElements();
    const container = ui.elements.cpTabProfile;
    if (!container) return;
    
    const viewDetailsHandler = (key) => {
        const profile = profiles.find(p => p.key === key);
        if (profile) {
            renderProfileDetailsModal(profile); 
            ui.showModal('profile'); // <-- Corrected to 'profile'
        }
    };
    
    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Choose a Persona</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-6 text-sm">Select a profile to define the AI's values, worldview, and rules. The chat will reload to apply the change.</p>
        <div class="space-y-4" role="radiogroup">
            ${profiles.map(profile => {
                const avatarUrl = getAvatarForProfile(profile.name);
                // Use description_short if available, fallback to description, then empty
                const description = profile.description_short || profile.description || '';
                return `
                <div class="p-4 border ${profile.key === activeProfileKey ? 'border-green-600 bg-green-50 dark:bg-green-900/30' : 'border-neutral-300 dark:border-neutral-700'} rounded-lg transition-colors">
                    <label class="flex items-center justify-between cursor-pointer">
                        <div class="flex items-center gap-3">
                            <img src="${avatarUrl}" alt="${profile.name} Avatar" class="w-8 h-8 rounded-lg">
                            <span class="font-semibold text-base text-neutral-800 dark:text-neutral-200">${profile.name}</span>
                        </div>
                        <input type="radio" name="ethical-profile" value="${profile.key}" class="form-radio text-green-600 focus:ring-green-500" ${profile.key === activeProfileKey ? 'checked' : ''}>
                    </label>
                    <p class="text-sm text-neutral-600 dark:text-neutral-300 mt-2">${description}</p>
                    <div class="mt-3">
                        <button data-key="${profile.key}" class="view-profile-details-btn text-sm font-medium text-green-600 dark:text-green-500 hover:underline">
                            View Details
                        </button>
                    </div>
                </div>
            `}).join('')}
        </div>
    `;

    container.querySelectorAll('input[name="ethical-profile"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            onProfileChange(e.target.value);
            container.querySelectorAll('.p-4.border').forEach(label => {
                label.classList.remove('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
                label.classList.add('border-neutral-300', 'dark:border-neutral-700');
            });
            radio.closest('.p-4.border').classList.add('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
            radio.closest('.p-4.border').classList.remove('border-neutral-300', 'dark:border-neutral-700');
        });
    });
    
    container.querySelectorAll('.view-profile-details-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            viewDetailsHandler(btn.dataset.key);
        });
    });
}

export function renderSettingsModelsTab(availableModels, user, onModelsSave) {
    ui._ensureElements();
    const container = ui.elements.cpTabModels;
    if (!container) return;
    
    const createSelect = (id, label, selectedValue) => `
        <div>
            <label for="${id}" class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">${label}</label>
            <select id="${id}" class="settings-modal-select">
                ${availableModels.map(model => `
                    <option value="${model}" ${model === selectedValue ? 'selected' : ''}>${model}</option>
                `).join('')}
            </select>
        </div>
    `;

    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Choose AI Models</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-6 text-sm">Assign a specific AI model to each of the three faculties. Changes will apply on the next page load.</p>
        <div class="space-y-4">
            ${createSelect('model-select-intellect', 'Intellect (Generation)', user.intellect_model)}
            ${createSelect('model-select-will', 'Will (Gatekeeping)', user.will_model)}
            ${createSelect('model-select-conscience', 'Conscience (Auditing)', user.conscience_model)}
        </div>
        <div class="mt-6 text-right">
            <button id="save-models-btn" class="px-5 py-2.5 rounded-lg font-semibold bg-green-600 text-white hover:bg-green-700 text-sm transition-colors">
                Save Changes
            </button>
        </div>
    `;

    document.getElementById('save-models-btn').addEventListener('click', () => {
        const newModels = {
            intellect_model: document.getElementById('model-select-intellect').value,
            will_model: document.getElementById('model-select-will').value,
            conscience_model: document.getElementById('model-select-conscience').value,
        };
        onModelsSave(newModels);
    });
}

export function renderSettingsDashboardTab() {
    ui._ensureElements();
    const container = ui.elements.cpTabDashboard;
    if (!container) return;

    if (container.querySelector('iframe')) return;

    container.innerHTML = ''; 

    const headerDiv = document.createElement('div');
    headerDiv.className = "p-6 shrink-0";
    headerDiv.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">Trace & Analyze</h3>
        <p class="text-neutral-500 dark:text-neutral-400 mb-0 text-sm">Analyze ethical alignment and trace decisions across all conversations.</p>
    `;
    
    const iframeContainer = document.createElement('div');
    iframeContainer.className = "w-full h-[1024px] overflow-hidden";

    const iframe = document.createElement('iframe');
    iframe.src = "https://dashboard.selfalignmentframework.com/?embed=true";
    iframe.className = "w-full h-full rounded-lg"; 
    iframe.title = "SAFi Dashboard";
    iframe.sandbox = "allow-scripts allow-same-origin allow-forms";
    
    iframeContainer.appendChild(iframe);

    container.appendChild(headerDiv);
    container.appendChild(iframeContainer);
}

export function renderSettingsAppTab(currentTheme, onThemeChange, onLogout, onDelete) {
    ui._ensureElements();
    const container = ui.elements.cpTabAppSettings;
    if (!container) return;

    const themes = [
        { key: 'light', name: 'Light' },
        { key: 'dark', name: 'Dark' },
        { key: 'system', name: 'System Default' }
    ];

    container.innerHTML = `
        <h3 class="text-xl font-semibold mb-4">App Settings</h3>
        
        <div class_="space-y-4">
            <h4 class="text-base font-semibold text-neutral-700 dark:text-neutral-300 mb-2">Theme</h4>
            <div class="space-y-2" role="radiogroup">
                ${themes.map(theme => `
                    <label class="flex items-center gap-3 p-3 border ${theme.key === currentTheme ? 'border-green-600 bg-green-50 dark:bg-green-900/30' : 'border-neutral-300 dark:border-neutral-700'} rounded-lg cursor-pointer hover:border-green-500 dark:hover:border-green-400 transition-colors">
                        <input type="radio" name="theme-select" value="${theme.key}" class="form-radio text-green-600 focus:ring-green-500" ${theme.key === currentTheme ? 'checked' : ''}>
                        <span class="text-sm font-medium text-neutral-800 dark:text-neutral-200">${theme.name}</span>
                    </label>
                `).join('')}
            </div>
            
            <h4 class="text-base font-semibold text-neutral-700 dark:text-neutral-300 mt-8 mb-2">Account</h4>
            <div class="space-y-3">
                <button id="cp-logout-btn" class="w-full text-left px-4 py-3 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-800 rounded-lg border border-neutral-300 dark:border-neutral-700 transition-colors">
                    Sign Out
                </button>
                <button id="cp-delete-account-btn" class="w-full text-left px-4 py-3 text-sm font-medium text-red-600 dark:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg border border-red-300 dark:border-red-700 transition-colors">
                    Delete Account...
                </button>
            </div>
        </div>
    `;

    container.querySelectorAll('input[name="theme-select"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            const newTheme = e.target.value;
            onThemeChange(newTheme);
            
            container.querySelectorAll('label').forEach(label => {
                label.classList.remove('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
                label.classList.add('border-neutral-300', 'dark:border-neutral-700');
            });
            radio.closest('label').classList.add('border-green-600', 'bg-green-50', 'dark:bg-green-900/30');
            radio.closest('label').classList.remove('border-neutral-300', 'dark:border-neutral-700');
        });
    });

    document.getElementById('cp-logout-btn').addEventListener('click', onLogout);
    document.getElementById('cp-delete-account-btn').addEventListener('click', onDelete);
}

// --- CONSCIENCE MODAL RENDERING ---

export function setupConscienceModalContent(payload) {
    ui._ensureElements();
    const container = ui.elements.conscienceDetails;
    if (!container) return;
    container.innerHTML = ''; 

    container.insertAdjacentHTML('beforeend', renderIntro(payload));
    container.insertAdjacentHTML('beforeend', renderScoreAndTrend(payload));
    container.insertAdjacentHTML('beforeend', renderLedger(payload.ledger));
    
    container.querySelectorAll('.expand-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const reason = btn.parentElement.querySelector('.reason-text');
            const isTruncated = reason.classList.contains('truncated');
            reason.classList.toggle('truncated');
            btn.textContent = isTruncated ? 'Show Less' : 'Show More';
        });
    });

    const copyBtn = document.getElementById('copy-audit-btn');
    if (copyBtn) {
        const newCopyBtn = copyBtn.cloneNode(true);
        copyBtn.parentNode.replaceChild(newCopyBtn, copyBtn);
        newCopyBtn.addEventListener('click', () => copyAuditToClipboard(payload));
    }
}

function renderIntro(payload) {
    const profileName = payload.profile ? `the <strong>${payload.profile}</strong>` : 'the current';
    return `<p class="text-base text-neutral-600 dark:text-neutral-300 mb-6">This response was shaped by ${profileName} ethical profile. Here’s a breakdown of the reasoning:</p>`;
}

function renderScoreAndTrend(payload) {
    if (payload.spirit_score === null || payload.spirit_score === undefined) return '';

    const score = Math.max(0, Math.min(10, payload.spirit_score));
    const circumference = 50 * 2 * Math.PI;
    const offset = circumference - (score / 10) * circumference;

    const getScoreColor = (s) => {
        if (s >= 8) return 'text-green-500';
        if (s >= 5) return 'text-yellow-500';
        return 'text-red-500';
    };
    
    const colorClass = getScoreColor(score);

    const radialGauge = `
        <div class="relative flex flex-col items-center justify-center">
            <svg class="w-32 h-32 transform -rotate-90">
                <circle class="text-neutral-200 dark:text-neutral-700" stroke-width="8" stroke="currentColor" fill="transparent" r="50" cx="64" cy="64" />
                <circle class="${colorClass.replace('text-', 'stroke-')}" stroke-width="8" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" stroke-linecap="round" stroke="currentColor" fill="transparent" r="50" cx="64" cy="64" />
            </svg>
            <div class="absolute flex flex-col items-center">
                 <span class="text-3xl font-bold ${colorClass}">${score.toFixed(1)}</span>
                 <span class="text-xs text-neutral-500 dark:text-neutral-400">/ 10</span>
            </div>
        </div>
        <h4 class="font-semibold mt-2 text-center">Alignment Score</h4>
        <p class="text-xs text-neutral-500 dark:text-neutral-400 mt-1 text-center max-w-[180px]">Reflects alignment with the active value set.</p>
    `;

    const scores = (payload.spirit_scores_history || []).filter(s => s !== null && s !== undefined).slice(-10);
    let sparkline = '<div class="flex-1 flex items-center justify-center text-sm text-neutral-400">Not enough data for trend.</div>';

    if (scores.length > 1) {
        const width = 200, height = 60, padding = 5;
        const maxScore = 10, minScore = 0;
        const range = maxScore - minScore;
        const points = scores.map((s, i) => {
            const x = (i / (scores.length - 1)) * (width - 2 * padding) + padding;
            const y = height - padding - ((s - minScore) / range) * (height - 2 * padding);
            return `${x},${y}`;
        }).join(' ');

        const lastPoint = points.split(' ').pop().split(',');
        sparkline = `
            <div class="flex-1 pl-4">
                <h4 class="font-semibold mb-2 text-center">Alignment Trend</h4>
                <svg viewBox="0 0 ${width} ${height}" class="w-full h-auto">
                    <polyline fill="none" class="stroke-green-500" stroke-width="2" points="${points}" />
                    <circle fill="${getScoreColor(scores[scores.length-1]).replace('text-','fill-')}" class="stroke-white dark:stroke-neutral-800" r="3" cx="${lastPoint[0]}" cy="${lastPoint[1]}"></circle>
                </svg>
                <p class="text-xs text-neutral-500 dark:text-neutral-400 mt-1 text-center">Recent score history</p>
            </div>
        `;
    }

    return `<div class="grid grid-cols-1 sm:grid-cols-2 gap-6 items-center bg-neutral-50 dark:bg-neutral-800/50 rounded-lg p-4 mb-6">${radialGauge}${sparkline}</div>`;
}

function renderLedger(ledger) {
    if (!ledger || ledger.length === 0) {
        return '<div class="text-sm text-center text-neutral-500 py-4">No specific values were engaged for this response.</div>';
    }

    const groups = {
        upholds: ledger.filter(r => r.score > 0),
        conflicts: ledger.filter(r => r.score < 0),
        neutral: ledger.filter(r => r.score === 0),
    };

    for (const key in groups) {
        groups[key].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    }

    const groupConfig = {
        upholds: { title: 'Upholds', icon: 'M5 13l4 4L19 7', color: 'green' },
        conflicts: { title: 'Conflicts', icon: 'M6 18L18 6M6 6l12 12', color: 'red' },
        neutral: { title: 'Neutral', icon: 'M18 12H6', color: 'neutral' },
    };

    let html = '';
    for (const key of ['upholds', 'conflicts', 'neutral']) {
        if (groups[key].length > 0) {
            const config = groupConfig[key];
            html += `
                <div class="flex items-center gap-3 my-4">
                    <span class="p-1.5 bg-${config.color}-100 dark:bg-${config.color}-900/40 rounded-full">
                        <svg class="w-5 h-5 text-${config.color}-600 dark:text-${config.color}-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${config.icon}"></path></svg>
                    </span>
                    <h4 class="text-base font-semibold text-neutral-800 dark:text-neutral-200">${config.title} (${groups[key].length})</h4>
                    <div class="flex-1 h-px bg-neutral-200 dark:bg-neutral-700"></div>
                </div>
                <div class="space-y-3">
                    ${groups[key].map(renderLedgerItem).join('')}
                </div>
            `;
        }
    }
    return html;
}

function renderLedgerItem(item) {
    const reasonHtml = DOMPurify.sanitize(String(item.reason || ''));
    const maxLength = 120;
    const isLong = reasonHtml.length > maxLength;
    
    const confidenceDisplayHtml = item.confidence ? `
        <div class="flex items-center gap-2 w-full sm:w-auto sm:min-w-[160px]">
            <span class="text-xs font-medium text-neutral-500 dark:text-neutral-400 hidden sm:inline">Confidence</span>
            <div class="h-1.5 flex-1 rounded-full bg-neutral-200 dark:bg-neutral-700">
                <div class="h-full rounded-full bg-green-500" style="width: ${item.confidence * 100}%"></div>
            </div>
            <span class="text-xs font-semibold text-neutral-600 dark:text-neutral-300 w-9 text-right">${Math.round(item.confidence * 100)}%</span>
        </div>
    ` : '';

    return `
        <div class="bg-white dark:bg-neutral-800/60 p-4 rounded-lg border border-neutral-200 dark:border-neutral-700/80">
            <div class="flex items-start sm:items-center justify-between gap-4 mb-2 flex-col sm:flex-row">
                <div class="font-semibold text-neutral-800 dark:text-neutral-200">${item.value}</div>
                ${confidenceDisplayHtml}
            </div>
            <div class="prose prose-sm dark:prose-invert max-w-none text-neutral-600 dark:text-neutral-400">
                <div class="reason-text ${isLong ? 'truncated' : ''}">${reasonHtml}</div>
                ${isLong ? '<button class="expand-btn">Show More</button>' : ''}
            </div>
        </div>
    `;
}

function copyAuditToClipboard(payload) {
    let text = `SAFi Ethical Reasoning Audit\n`;
    text += `Profile: ${payload.profile || 'N/A'}\n`;
    text += `Alignment Score: ${payload.spirit_score !== null ? payload.spirit_score.toFixed(1) + '/10' : 'N/A'}\n`;
    text += `------------------------------------\n\n`;
    
    if (payload.ledger && payload.ledger.length > 0) {
        const upholds = payload.ledger.filter(r => r.score > 0);
        const conflicts = payload.ledger.filter(r => r.score < 0);
        const neutral = payload.ledger.filter(r => r.score === 0);

        if (upholds.length > 0) {
            text += 'UPHOLDS:\n';
            upholds.forEach(item => {
                text += `- ${item.value} (Confidence: ${Math.round((item.confidence || 0) * 100)}%): ${item.reason}\n`;
            });
            text += '\n';
        }
        if (conflicts.length > 0) {
            text += 'CONFLICTS:\n';
            conflicts.forEach(item => {
                text += `- ${item.value} (Confidence: ${Math.round((item.confidence || 0) * 100)}%): ${item.reason}\n`;
            });
            text += '\n';
        }
        if (neutral.length > 0) {
            text += 'NEUTRAL:\n';
            neutral.forEach(item => {
                text += `- ${item.value} (Confidence: ${Math.round((item.confidence || 0) * 100)}%): ${item.reason}\n`;
            });
        }
    } else {
        text += 'No specific values were engaged for this response.';
    }

    navigator.clipboard.writeText(text).then(() => {
        ui.showToast('Audit copied to clipboard', 'success');
    }, () => {
        ui.showToast('Failed to copy audit', 'error');
    });
}

// --- START: PROFILE DETAILS MODAL ---

/**
 * Helper to create a formatted section for the profile details modal.
 * @param {string} title - The title of the section (e.g., "Worldview")
 * @param {string | string[]} content - The content (string for markdown, array for lists)
 * @returns {string} - The HTML string for the section
 */
function createModalSection(title, content) {
    if (!content) return '';
    
    let contentHtml = '';
    
    // Check if content is an array (for will_rules)
    if (Array.isArray(content)) {
        if (content.length === 0) return '';
        contentHtml = '<ul class="space-y-1">' + content.map(item => `<li class="flex gap-2"><span class="opacity-60">»</span><span class="flex-1">${item}</span></li>`).join('') + '</ul>';
    } else {
        // Render markdown for strings
        contentHtml = DOMPurify.sanitize(marked.parse(String(content ?? '')));
    }

    return `
        <div class="mb-6">
            <h3 class="text-lg font-semibold text-neutral-800 dark:text-neutral-200 mb-3">${title}</h3>
            <div class="prose prose-sm dark:prose-invert max-w-none text-neutral-700 dark:text-neutral-300">
                ${contentHtml}
            </div>
        </div>
    `;
}

/**
 * Creates the HTML for the "Values" section, including rubrics.
 * @param {Array} values - The array of value objects from the profile
 * @returns {string} - The HTML string for the values section
 */
function renderValuesSection(values) {
    if (!values || values.length === 0) return '';

    const valuesHtml = values.map(v => {
        let rubricHtml = '';
        if (v.rubric) {
            
            // --- MODIFICATION: Added color-coding and styling to scoring guide ---
            const scoringGuideHtml = (v.rubric.scoring_guide || []).map(g => {
                let scoreClasses = '';
                let scoreText = String(g.score); // Default text

                if (g.score > 0) {
                    scoreClasses = 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300';
                    scoreText = `+${g.score.toFixed(1)}`; // Format to one decimal place
                } else if (g.score === 0) {
                    scoreClasses = 'bg-neutral-100 text-neutral-800 dark:bg-neutral-700 dark:text-neutral-300';
                    scoreText = g.score.toFixed(1); // Format to one decimal place
                } else { // g.score < 0
                    scoreClasses = 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300';
                    scoreText = g.score.toFixed(1); // Format to one decimal place
                }
                
                // Create a styled "chip" for the score
                const scoreChipHtml = `<span class="inline-block text-xs font-mono font-bold px-1.5 py-0.5 rounded ${scoreClasses}">${scoreText}</span>`;
                
                // Use flexbox for alignment
                return `<li class="mb-1.5 flex items-start gap-2">
                            <div class="flex-shrink-0 w-12 text-center mt-0.5">${scoreChipHtml}</div>
                            <div class="flex-1">${g.descriptor}</div>
                        </li>`;
            }).join('');
            // --- END MODIFICATION ---
            
            rubricHtml = `
                <div class="mt-3 pl-4 border-l-2 border-neutral-200 dark:border-neutral-700">
                    <h6 class="font-semibold text-neutral-700 dark:text-neutral-300">Rubric Description:</h6>
                    <p class="italic text-sm">${v.rubric.description || 'N/A'}</p>
                    <h6 class="font-semibold text-neutral-700 dark:text-neutral-300 mt-3">Scoring Guide:</h6>
                    <ul class="list-none pl-0 mt-2">${scoringGuideHtml}</ul>
                </div>
            `;
        }
        
        return `
            <div class="mb-3">
                <h5 class="text-base font-semibold text-neutral-800 dark:text-neutral-200">${v.value}</h5>
                <p class="mb-1 text-sm">${v.definition || 'No definition provided.'}</p>
                ${rubricHtml}
            </div>
        `;
    }).join('<hr class="my-4 border-neutral-200 dark:border-neutral-700">');

    return `
        <div class="mb-6">
            <h3 class="text-lg font-semibold text-neutral-800 dark:text-neutral-200 mb-3">Values</h3>
            <div class="prose prose-sm dark:prose-invert max-w-none text-neutral-700 dark:text-neutral-300">
                ${valuesHtml}
            </div>
        </div>
    `;
}

/**
 * Populates the Profile Details modal with the given profile data.
 * @param {object} profile - The full profile object
 */
export function renderProfileDetailsModal(profile) {
    ui._ensureElements();
    const container = ui.elements.profileModalContent;
    if (!container) {
        console.error("Profile modal content area not found.");
        return;
    }

    // Set title
    const titleEl = document.getElementById('profile-modal-title');
    if (titleEl) titleEl.textContent = profile.name || 'Profile Details';

    // Clear previous content
    container.innerHTML = '';
    
    // --- RENDER SECTIONS IN THE REQUESTED ORDER ---
    container.insertAdjacentHTML('beforeend', createModalSection('Description', profile.description));
    container.insertAdjacentHTML('beforeend', createModalSection('Worldview', profile.worldview));
    container.insertAdjacentHTML('beforeend', createModalSection('Style', profile.style));
    container.insertAdjacentHTML('beforeend', renderValuesSection(profile.values));
    container.insertAdjacentHTML('beforeend', createModalSection('Rules (Non-Negotiable)', profile.will_rules));

    // Reset scroll to top
    container.scrollTop = 0;
}
// --- END: PROFILE DETAILS MODAL ---