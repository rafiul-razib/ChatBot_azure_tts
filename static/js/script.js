// ------------------------------------
// Timing & constants
// ------------------------------------
const BOT_REPLY_DELAY = 100;
const LISTEN_RESTART_DELAY = 100;
const USER_SILENCE_TIMEOUT = 5000;

// ------------------------------------
// Global state
// ------------------------------------
let recognition;
let isConversationActive = false;
let isBotSpeaking = false;
let recognitionReady = true;
let silenceTimer = null;
let audioUnlocked = false;
let currentAudio = null;
let lastUserLang = "en-US";
let currentAbortController = null;

// ------------------------------------
// DOM elements
// ------------------------------------
const micBtn = document.getElementById("micBtn");
const userInput = document.getElementById("user-input");
const chatBox = document.getElementById("chat-box");
const typingIndicator = document.getElementById("typingIndicator");

// ------------------------------------
// Detect Bangla text
// ------------------------------------
function isBangla(text) {
  return /[\u0980-\u09FF]/.test(text);
}

// ------------------------------------
// Unlock browser audio (required by Chrome)
// ------------------------------------
function unlockAudio() {
  if (audioUnlocked) return;
  const a = new Audio();
  a.play().catch(() => {});
  audioUnlocked = true;
}

// ------------------------------------
// Typing indicator helpers
// ------------------------------------
function showTyping() {
  if (typingIndicator) typingIndicator.style.display = "flex";
}

function hideTyping() {
  if (typingIndicator) typingIndicator.style.display = "none";
}

// ------------------------------------
// Initialize SpeechRecognition
// ------------------------------------
const SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition;

if (!SpeechRecognition) {
  micBtn.disabled = true;
  micBtn.innerText = "🎤 Not supported";
} else {
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onstart = () => {
    recognitionReady = false;
    micBtn.classList.add("pulsing");
    startSilenceTimer();
  };

  recognition.onend = () => {
    recognitionReady = true;
    micBtn.classList.remove("pulsing");
    clearTimeout(silenceTimer);

    if (isConversationActive && !isBotSpeaking) {
      setTimeout(safeStartRecognition, LISTEN_RESTART_DELAY);
    }
  };

  recognition.onerror = () => recognition.stop();
}

// ------------------------------------
// Mic button (toggle conversation)
// ------------------------------------
micBtn.onclick = () => {
  unlockAudio();

  if (isConversationActive) {
    isConversationActive = false;
    stopAll();
    micBtn.classList.remove("pulsing");
  } else {
    interruptBot();
    isConversationActive = true;
    safeStartRecognition();
  }
};

// ------------------------------------
// Stop everything
// ------------------------------------
function stopAll() {
  interruptBot();
  clearTimeout(silenceTimer);
  try {
    recognition.stop();
  } catch {}
}

// ------------------------------------
// HARD interrupt: stop bot audio & pending fetch
// ------------------------------------
function interruptBot() {
  if (currentAbortController) {
    currentAbortController.abort();
    currentAbortController = null;
  }
  stopBotSpeech();
}

// ------------------------------------
// Silence timeout
// ------------------------------------
function startSilenceTimer() {
  clearTimeout(silenceTimer);
  silenceTimer = setTimeout(() => {
    if (isConversationActive && !isBotSpeaking) {
      try {
        recognition.stop();
      } catch {}
    }
  }, USER_SILENCE_TIMEOUT);
}

// ------------------------------------
// Safe STT start
// ------------------------------------
function safeStartRecognition() {
  if (!isConversationActive || isBotSpeaking || !recognitionReady) return;

  tryLang("bn-BD", (found) => {
    if (!found) tryLang("en-US");
  });
}

// ------------------------------------
// Try recognition with language
// ------------------------------------
function tryLang(lang, callback) {
  if (isBotSpeaking) return;

  recognition.lang = lang;

  recognition.onresult = async (e) => {
    if (isBotSpeaking) {
      recognition.stop();
      return;
    }

    const text = e.results[0][0].transcript.trim();
    if (!text) {
      recognition.stop();
      callback?.(false);
      return;
    }

    interruptBot();
    recognition.stop();
    lastUserLang = lang;
    userInput.value = text;
    await sendMessage(text);
    callback?.(true);
  };

  recognition.onerror = () => {
    recognition.stop();
    callback?.(false);
  };

  recognition.start();
}

// ------------------------------------
// Add chat messages (HTML-matched)
// ------------------------------------
function addMessage(sender, text, type) {
  const msg = document.createElement("div");
  msg.className = `message ${type}`;

    // Choose avatar: 👤 for user, 💄 for bot
  const avatar = type === "user" ? "👤" : "💄";

  msg.innerHTML = `
    <div class="message-avatar">${avatar}</div>
    <div class="message-content">
      <div class="message-bubble">
        ${sender ? `<strong>${sender}</strong>` : ""}
        <p>${text}</p>
      </div>
      <span class="message-time">Now</span>
    </div>
  `;

  chatBox.appendChild(msg);
  chatBox.scrollTop = chatBox.scrollHeight;
}

// ------------------------------------
// Stop bot TTS
// ------------------------------------
function stopBotSpeech() {
  isBotSpeaking = false;
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
    currentAudio = null;
  }
}

// ------------------------------------
// Speak bot reply
// ------------------------------------
async function speakBot(text) {
  if (!text || !isConversationActive) return;

  isBotSpeaking = true;
  try {
    recognition.stop();
  } catch {}

  try {
    const res = await fetch("/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });

    const { audio_url } = await res.json();
    if (!audio_url) throw new Error("TTS failed");

    currentAudio = new Audio(audio_url + "?t=" + Date.now());
    currentAudio.play();

    currentAudio.onended = () => {
      isBotSpeaking = false;
      currentAudio = null;
      setTimeout(safeStartRecognition, LISTEN_RESTART_DELAY);
    };

    currentAudio.onerror = () => {
      isBotSpeaking = false;
      currentAudio = null;
    };
  } catch {
    isBotSpeaking = false;
  }
}

// ------------------------------------
// Send message to AI
// ------------------------------------
async function sendMessageInternal(msg) {
  if (!msg) return;

  interruptBot();

  // Add user message first
  addMessage("", msg, "user");
  userInput.value = "";

  // Show typing indicator immediately after
  showTyping();

  currentAbortController = new AbortController();

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg }),
      signal: currentAbortController.signal,
    });

    const data = await res.json();

    // Hide typing and show bot reply
    setTimeout(() => {
      hideTyping();
      addMessage("Lira AI", data.reply, "bot");
      speakBot(data.reply);
    }, BOT_REPLY_DELAY);

  } catch (e) {
    hideTyping();
    if (e.name !== "AbortError") {
      addMessage("Lira AI", "Something went wrong.", "bot");
    }
  } finally {
    currentAbortController = null;
  }
}



 const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
      themeToggle.addEventListener('click', () => {
        document.body.classList.toggle('dark-mode');
      });
    }

// ------------------------------------
// Expose sendMessage for HTML buttons
// ------------------------------------
window.sendMessage = (msgFromUI) => {
  console.log("message sent");
  const msg = msgFromUI ?? userInput.value.trim();
  if (msg) sendMessageInternal(msg);
};

