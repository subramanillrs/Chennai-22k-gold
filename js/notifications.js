// ============================================================
// NOTIFICATIONS, AUDIO SYNTHESIS & HAPTICS
// ============================================================
let audioCtx = null;
function playTick(freq = 800, duration = 0.015) {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
    gain.gain.setValueAtTime(0.03, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + duration);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + duration);
  } catch(_) {}
}

const haptic = (ms = 10, freq = 800) => {
  if ("vibrate" in navigator) { try { navigator.vibrate(ms); } catch (_) {} }
  playTick(freq);
};

/**
 * Web Audio API Gold Coin Acoustic Resonance Synthesizer (22k-Pro)
 * 
 * Physical Acoustics of Pure Gold Bullion (22K / 24K):
 * - High mass density (17.5-19.3 g/cm³) produces a distinct, crystalline metallic ping.
 * - Characteristic circular plate flexural modes:
 *     Fundamental mode (0,2):  ~2800 Hz
 *     Harmonic overtone mode (0,3): ~4200 Hz (1.5x harmonic ratio)
 * - Exponential decay envelope: 0.35s natural acoustic ringdown.
 * - 5800 Hz lowpass filter tames harsh DAC step noise and shapes warm bullion luster.
 * 
 * @param {number} [pitchModifier=1.0] - Pitch multiplier (e.g. 1.0 for 22K sovereign, 0.95 for heavy 24K bar, 1.08 for 1g coin)
 */
function playGoldCoinChime(pitchModifier = 1.0) {
  try {
    if (!audioCtx) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return;
      audioCtx = new AudioContextClass();
    }
    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => {});
    }

    const mod = (typeof pitchModifier === 'number' && Number.isFinite(pitchModifier) && pitchModifier > 0)
      ? pitchModifier
      : 1.0;

    const now = audioCtx.currentTime;
    const decayDuration = 0.35;
    const f1 = 2800 * mod;
    const f2 = 4200 * mod;

    // 1. Dual High-Frequency Oscillators (Sine for pure metallic ring)
    const osc1 = audioCtx.createOscillator();
    const osc2 = audioCtx.createOscillator();
    osc1.type = "sine";
    osc2.type = "sine";
    osc1.frequency.setValueAtTime(f1, now);
    osc2.frequency.setValueAtTime(f2, now);

    // 2. Low-Pass Acoustic Filter (warms metallic ring & suppresses aliasing)
    const filter = audioCtx.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.setValueAtTime(5800 * mod, now);
    filter.Q.setValueAtTime(1.5, now);

    // 3. Exponential Decay Gain Envelope (clickless 2ms attack + 0.35s exponential ringdown)
    const gainNode = audioCtx.createGain();
    const peakGain = 0.12;
    gainNode.gain.setValueAtTime(0.0001, now);
    gainNode.gain.linearRampToValueAtTime(peakGain, now + 0.002);
    gainNode.gain.exponentialRampToValueAtTime(0.00001, now + decayDuration);

    // 4. Audio Routing: [osc1, osc2] -> gainNode -> filter -> destination
    osc1.connect(gainNode);
    osc2.connect(gainNode);
    gainNode.connect(filter);
    filter.connect(audioCtx.destination);

    // 5. Trigger playback & schedule release
    osc1.start(now);
    osc2.start(now);
    osc1.stop(now + decayDuration);
    osc2.stop(now + decayDuration);

    // 6. Automatic garbage collection on ring completion
    osc1.onended = () => {
      try {
        osc1.disconnect();
        osc2.disconnect();
        gainNode.disconnect();
        filter.disconnect();
      } catch (_) {}
    };
  } catch (_) {}
}
window.playGoldCoinChime = playGoldCoinChime;

// Safe proactive audio unlock on user gesture
if (typeof document !== 'undefined') {
  const unlockAudio = () => {
    try {
      if (!audioCtx) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (AudioContextClass) audioCtx = new AudioContextClass();
      }
      if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume().catch(() => {});
      }
    } catch (_) {}
    document.removeEventListener('pointerdown', unlockAudio);
    document.removeEventListener('keydown', unlockAudio);
  };
  document.addEventListener('pointerdown', unlockAudio, { passive: true, once: true });
  document.addEventListener('keydown', unlockAudio, { passive: true, once: true });
}

function toast(text) {
  const el = $("toast");
  if (!el) return;
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 2800);
}

function triggerHaptic(ms = 10) {
  if (typeof navigator !== "undefined" && navigator.vibrate) {
    try { navigator.vibrate(ms); } catch (_) {}
  }
}

function playSynthesizerChime() {
  if (typeof playGoldCoinChime === "function") {
    playGoldCoinChime(1.15);
  } else if (typeof playTick === "function") {
    playTick(1200, 0.05);
  }
}

function sendBrowserNotification(title, options = {}) {
  if (typeof Notification !== "undefined" && Notification.permission === "granted") {
    try {
      new Notification(title, {
        icon: "icon.svg",
        badge: "icon.svg",
        ...options
      });
    } catch (_) {}
  }
}

window.toast = toast;
window.triggerHaptic = triggerHaptic;
window.haptic = haptic;
window.playTick = playTick;
window.playGoldCoinChime = playGoldCoinChime;
window.playSynthesizerChime = playSynthesizerChime;
window.sendBrowserNotification = sendBrowserNotification;
