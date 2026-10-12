(async () => {
  const s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
  const r = new SpeechRecognition();
  r.lang = "__LANG__"; r.continuous = true; r.interimResults = true; 
  r.onresult = (e) => { for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) console.log("FINAL " + e.results[i][0].transcript); };
  r.onerror = (e) => console.log("ERROR " + e.error + " " + (e.message || ""));
  r.start(s.getAudioTracks()[0]);
  return "started local";
})()
