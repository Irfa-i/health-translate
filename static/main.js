// main.js
const startBtn = document.getElementById("startRec");
const stopBtn = document.getElementById("stopRec");
const playBtn = document.getElementById("playTrans");
const origArea = document.getElementById("orig");
const translatedDiv = document.getElementById("translated");
const sourceLang = document.getElementById("sourceLang");
const targetLang = document.getElementById("targetLang");

let recognition = null;
let finalTranscript = "";

function supportsSpeech() {
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

if (supportsSpeech()) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SR();
  recognition.interimResults = true;
  recognition.continuous = true;

  recognition.onresult = (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; ++i) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        finalTranscript += transcript + " ";
      } else {
        interim += transcript;
      }
    }
    origArea.value = (finalTranscript + interim).trim();
  };

  recognition.onerror = (e) => {
    console.error("Recognition error", e);
  };

  recognition.onend = () => {
    startBtn.disabled = false;
    stopBtn.disabled = true;
    // Auto-submit final transcript for translation
    if (origArea.value.trim()) {
      sendForTranslation(origArea.value.trim());
    }
  };
} else {
  startBtn.disabled = true;
  alert("Sorry — your browser doesn't support the Web Speech API. Use Chrome on desktop or Android/iOS Chrome.");
}

startBtn.onclick = () => {
  finalTranscript = "";
  origArea.value = "";
  translatedDiv.textContent = "Translating...";
  recognition.lang = mapLangCode(sourceLang.value) || "en-US";
  recognition.start();
  startBtn.disabled = true;
  stopBtn.disabled = false;
};

stopBtn.onclick = () => {
  recognition.stop();
  stopBtn.disabled = true;
};

playBtn.onclick = () => {
  const t = translatedDiv.textContent || "";
  if (!t) return;
  speakText(t, targetLang.value);
};

function mapLangCode(code) {
  const map = {
    "en": "en-US",
    "es": "es-ES",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "auto": "en-US"
  };
  return map[code] || "en-US";
}

async function sendForTranslation(text) {
  translatedDiv.textContent = "Translating...";
  playBtn.disabled = true;
  try {
    const resp = await fetch("/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text, source: sourceLang.value, target: targetLang.value })
    });
    const j = await resp.json();
    if (j.error) {
      translatedDiv.textContent = "Error: " + (j.detail || j.error);
      return;
    }
    translatedDiv.textContent = j.translated || "(no translation)";
    playBtn.disabled = false;
  } catch (err) {
    translatedDiv.textContent = "Network error: " + err;
  }
}

function speakText(text, lang) {
  if (!("speechSynthesis" in window)) {
    alert("SpeechSynthesis not supported in this browser.");
    return;
  }
  const utter = new SpeechSynthesisUtterance(text);
  const voices = window.speechSynthesis.getVoices();
  if (voices && voices.length) {
    const v = voices.find(x => x.lang && x.lang.startsWith(mapLocaleFromCode(lang)));
    if (v) utter.voice = v;
  }
  utter.rate = 1;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utter);
}

function mapLocaleFromCode(code) {
  const m = { en: "en", es: "es", hi: "hi", ta: "ta" };
  return m[code] || "en";
}
