import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';

// Static import for default English language
import enUS from '../translations/en-US.json';

const FALLBACK = 'en-US';

// Dynamically glob other translation files
const lazyModules = import.meta.glob('../translations/*.json');

function moduleKeyFor(code: string): string {
  return `../translations/${code}.json`;
}

// Read saved language from localStorage (matching 3x-ui standard)
let active = localStorage.getItem('lang') || FALLBACK;
if (active !== FALLBACK && !Object.prototype.hasOwnProperty.call(lazyModules, moduleKeyFor(active))) {
  active = FALLBACK;
}

export async function readyI18n() {
  await i18next.use(initReactI18next).init({
    lng: active,
    fallbackLng: FALLBACK,
    resources: { [FALLBACK]: { translation: enUS } },
    interpolation: { escapeValue: false },
    returnNull: false,
  });

  if (active !== FALLBACK) {
    const loader = lazyModules[moduleKeyFor(active)] as (() => Promise<{ default: any }>) | undefined;
    if (loader) {
      const mod = await loader();
      const messages = (mod.default ?? mod) as Record<string, any>;
      i18next.addResourceBundle(active, 'translation', messages, true, true);
      await i18next.changeLanguage(active);
    }
  }
  return i18next;
}

export { i18next as i18n };
export const SUPPORTED_LANGUAGES = [
  { code: 'en-US', label: 'English' },
  { code: 'id-ID', label: 'Bahasa Indonesia' },
  { code: 'zh-CN', label: '简体中文' },
  { code: 'zh-TW', label: '繁體中文' },
  { code: 'ru-RU', label: 'Русский' },
  { code: 'tr-TR', label: 'Türkçe' },
  { code: 'es-ES', label: 'Español' },
  { code: 'pt-BR', label: 'Português (Brasil)' },
  { code: 'vi-VN', label: 'Tiếng Việt' },
  { code: 'ar-EG', label: 'العربية' },
  { code: 'fa-IR', label: 'فارسی' },
  { code: 'ja-JP', label: '日本語' },
  { code: 'uk-UA', label: 'Українська' }
];
