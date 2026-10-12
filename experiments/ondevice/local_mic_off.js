(() => {
  const r = new SpeechRecognition();
  r.lang = "__LANG__"; r.continuous = true; r.interimResults = true; r.processLocally = false;
  r.onstart = () => console.log("START");
  r.onaudiostart = () => console.log("AUDIOSTART");
  r.onresult = (e) => { for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) console.log("FINAL " + e.results[i][0].transcript); };
  r.onerror = (e) => console.log("ERROR " + e.error + " " + (e.message || ""));
  r.onend = () => console.log("END");
  r.start();
  return "started default-mic local=" + false;
})()
