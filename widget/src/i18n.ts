export type Lang = "en" | "ur" | "roman_ur";

export const LANG_LABEL: Record<Lang, string> = { en: "EN", ur: "اردو", roman_ur: "Roman" };

const STRINGS = {
  title: { en: "Admissions help", ur: "داخلہ رہنمائی", roman_ur: "Admission help" },
  placeholder: {
    en: "Type your question…",
    ur: "اپنا سوال لکھیں…",
    roman_ur: "Apna sawal likhein…",
  },
  send: { en: "Send", ur: "بھیجیں", roman_ur: "Bhejein" },
  open: { en: "Chat with us", ur: "ہم سے بات کریں", roman_ur: "Hum se baat karein" },
  close: { en: "Close", ur: "بند کریں", roman_ur: "Band karein" },
  whatsapp: {
    en: "Continue on WhatsApp",
    ur: "واٹس ایپ پر جاری رکھیں",
    roman_ur: "WhatsApp par jaari rakhein",
  },
  pickSlot: { en: "Pick a time", ur: "وقت منتخب کریں", roman_ur: "Waqt chunein" },
  leadTitle: {
    en: "Share your details and the office will confirm",
    ur: "اپنی تفصیل دیں، دفتر تصدیق کرے گا",
    roman_ur: "Apni details dein, office confirm karega",
  },
  name: { en: "Your name", ur: "آپ کا نام", roman_ur: "Aap ka naam" },
  phone: { en: "Phone (03xx-xxxxxxx)", ur: "فون (03xx-xxxxxxx)", roman_ur: "Phone (03xx-xxxxxxx)" },
  submit: { en: "Submit", ur: "جمع کریں", roman_ur: "Submit" },
  thanks: {
    en: "Thank you! The office will contact you.",
    ur: "شکریہ! دفتر آپ سے رابطہ کرے گا۔",
    roman_ur: "Shukriya! Office aap se rabta karega.",
  },
  badPhone: {
    en: "Please enter a valid Pakistani number.",
    ur: "براہ کرم درست پاکستانی نمبر لکھیں۔",
    roman_ur: "Baraye meharbani sahi Pakistani number likhein.",
  },
  error: {
    en: "Sorry, something went wrong. Please try again.",
    ur: "معذرت، کچھ غلط ہو گیا۔ دوبارہ کوشش کریں۔",
    roman_ur: "Maazrat, kuch ghalat ho gaya. Dobara koshish karein.",
  },
  busy: {
    en: "Too many messages — please wait a few minutes.",
    ur: "بہت زیادہ پیغامات — چند منٹ انتظار کریں۔",
    roman_ur: "Bohat zyada messages — kuch minute intezar karein.",
  },
  source: { en: "Source", ur: "ماخذ", roman_ur: "Source" },
  page: { en: "p.", ur: "صفحہ", roman_ur: "p." },
  iWant: {
    en: "I'd like the slot on {slot}.",
    ur: "مجھے {slot} والا وقت چاہیے۔",
    roman_ur: "Mujhe {slot} wala slot chahiye.",
  },
  myDetails: {
    en: "My name is {name}, phone {phone}.",
    ur: "میرا نام {name} ہے، فون {phone}۔",
    roman_ur: "Mera naam {name} hai, phone {phone}.",
  },
  powered: {
    en: "AI assistant · answers from official documents",
    ur: "اے آئی معاون · سرکاری دستاویزات سے جوابات",
    roman_ur: "AI assistant · official documents se jawab",
  },
} as const;

export type Key = keyof typeof STRINGS;

export function t(key: Key, lang: Lang, vars: Record<string, string> = {}): string {
  return STRINGS[key][lang].replace(/\{(\w+)\}/g, (_, k: string) => vars[k] ?? "");
}

export function isRtl(lang: Lang): boolean {
  return lang === "ur";
}

let fontRequested = false;

/** Noto Nastaliq Urdu, loaded only when Urdu is selected. @font-face must live in the document
 * (not the shadow root) to apply inside it. */
export function loadUrduFont(): void {
  if (fontRequested) return;
  fontRequested = true;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href =
    "https://fonts.googleapis.com/css2?family=Noto+Nastaliq+Urdu:wght@400;600&display=swap";
  document.head.appendChild(link);
}
