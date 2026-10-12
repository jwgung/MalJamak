(async () => {
  const out = {};
  for (const lang of ["ko-KR", "en-US", "ja-JP"]) {
    try { out[lang] = await SpeechRecognition.available({ langs: [lang], processLocally: true }); }
    catch (e) { out[lang] = "error: " + e.message; }
  }
  return JSON.stringify(out);
})()
