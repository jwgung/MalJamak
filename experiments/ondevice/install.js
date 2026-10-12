(async () => {
  try { const ok = await SpeechRecognition.install({ langs: ["__LANG__"], processLocally: true }); return "install: " + ok; }
  catch (e) { return "install error: " + e.name + " " + e.message; }
})()
