// 화면들이 함께 쓰는 언어 목록. 음성 인식(구글)·번역(Groq·Chrome)은 이보다 많은 언어를 지원하지만,
// 고르기 쉽게 자주 쓸 만한 언어만 둔다. script: 그 언어 글자 체계 (순차통역 결과 거르기에 쓴다).
const LANGS = [
  { code: "ko-KR", name: "한국어", script: "Hangul" },
  { code: "en-US", name: "English", script: "Latin" },
  { code: "ja-JP", name: "日本語", script: "Japanese" },
  { code: "zh-CN", name: "中文 (简体)", script: "Han" },
  { code: "zh-TW", name: "中文 (繁體)", script: "Han" },
  { code: "es-ES", name: "Español", script: "Latin" },
  { code: "fr-FR", name: "Français", script: "Latin" },
  { code: "de-DE", name: "Deutsch", script: "Latin" },
  { code: "pt-BR", name: "Português", script: "Latin" },
  { code: "it-IT", name: "Italiano", script: "Latin" },
  { code: "ru-RU", name: "Русский", script: "Cyrillic" },
  { code: "uk-UA", name: "Українська", script: "Cyrillic" },
  { code: "mn-MN", name: "Монгол", script: "Cyrillic" },
  { code: "vi-VN", name: "Tiếng Việt", script: "Latin" },
  { code: "th-TH", name: "ไทย", script: "Thai" },
  { code: "id-ID", name: "Bahasa Indonesia", script: "Latin" },
  { code: "ms-MY", name: "Bahasa Melayu", script: "Latin" },
  { code: "fil-PH", name: "Filipino", script: "Latin" },
  { code: "hi-IN", name: "हिन्दी", script: "Devanagari" },
  { code: "ar-SA", name: "العربية", script: "Arabic" },
  { code: "tr-TR", name: "Türkçe", script: "Latin" },
  { code: "ne-NP", name: "नेपाली", script: "Devanagari" },
];

// <select> 를 언어 목록으로 채운다. 저장된 값이 목록에 없어도 사라지지 않게 그대로 한 줄 추가한다.
function fillLangSelect(select, value) {
  const keep = value ?? select.value;
  select.replaceChildren(...LANGS.map((l) => new Option(l.name, l.code)));
  if (keep && !LANGS.some((l) => l.code === keep)) select.add(new Option(keep, keep));
  if (keep) select.value = keep;
}

function isKorean(code) { return String(code || "").startsWith("ko"); }
