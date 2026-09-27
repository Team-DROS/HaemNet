// HaemNet design tokens for the hospital dashboard.
// Source of truth: design/tokens.json. Light-first: red is reserved for
// critical, failed and attention states; navy is the primary action colour.

import { Platform } from 'react-native';

const light = {
  canvas: '#F5F7FA',
  surface: '#FFFFFF',
  surface2: '#F8FAFC',
  selected: '#EDF2F9',
  track: '#F1F4F8',

  border: '#E4E8EF',
  borderSoft: '#EDF0F5',
  divider: '#F1F3F7',

  text: '#0F1A2B',
  primary: '#0F1A2B', primaryHover: '#1D2A40',
  text2: '#58637A',
  muted: '#8B95A7',
  faint: '#AEB6C4',
  disabled: '#C3CAD5',

  red: '#D92D20', redText: '#B42318', redSurface: '#FEF3F2', redBorder: '#F4D9D6', redBand: '#FFF9F8',
  green: '#0E9B6C', greenText: '#08734F', greenSurface: '#E7F6EF', greenBand: '#F0FAF5',
  blue: '#2E5FEA', blueText: '#1E46B8', blueSurface: '#EEF3FF',
  violet: '#6941F5', violetText: '#5B34D6', violetSurface: '#F3F0FF',
  amber: '#E49412', amberText: '#A96206', amberSurface: '#FFF8EB',
  slate: '#94A3B5', slateLight: '#CDD4DF',
};

const dark = {
  canvas: '#0B1220', surface: '#141E2E', surface2: '#1B283A',
  selected: '#25354C', track: '#243248',
  border: '#334257', borderSoft: '#2B394D', divider: '#263449',
  text: '#F3F6FB', primary: '#385DC3', primaryHover: '#466DD8', text2: '#C5D0DF', muted: '#A6B3C5', faint: '#8999AE', disabled: '#718096',
  red: '#F66B61', redText: '#FFAAA2', redSurface: '#432629', redBorder: '#714041', redBand: '#322126',
  green: '#30C895', greenText: '#74E4B9', greenSurface: '#173D35', greenBand: '#19332F',
  blue: '#719BFF', blueText: '#A9C1FF', blueSurface: '#223552',
  violet: '#AE94FF', violetText: '#C8B8FF', violetSurface: '#342B50',
  amber: '#F3B84E', amberText: '#FFD48A', amberSurface: '#493724',
  slate: '#A4B4C9', slateLight: '#72849A',
};

// CSS variables keep styles created at module load in sync with the web theme.
// Native builds retain the existing light palette.
export const color = Object.fromEntries(
  Object.entries(light).map(([key, value]) => [key, Platform.OS === 'web' ? `var(--hn-${key}, ${value})` : value]),
);

export function getSavedTheme() {
  if (Platform.OS !== 'web' || typeof window === 'undefined') return 'light';
  try { return window.localStorage.getItem('haemnet-theme') === 'dark' ? 'dark' : 'light'; }
  catch { return 'light'; }
}

export function applyWebTheme(theme) {
  if (Platform.OS !== 'web' || typeof document === 'undefined') return;
  const palette = theme === 'dark' ? dark : light;
  Object.entries(palette).forEach(([key, value]) => document.documentElement.style.setProperty(`--hn-${key}`, value));
  document.documentElement.style.colorScheme = theme === 'dark' ? 'dark' : 'light';
  try { window.localStorage.setItem('haemnet-theme', theme); } catch { /* storage may be unavailable */ }
}

const webOnly = (value, fallback) => (Platform.OS === 'web' ? value : fallback);

export const font = {
  display: webOnly("'Space Grotesk', system-ui, sans-serif", undefined),
  body: webOnly("'IBM Plex Sans', system-ui, sans-serif", undefined),
  mono: webOnly("'IBM Plex Mono', ui-monospace, monospace", 'monospace'),
};

export const radius = { chip: 6, control: 7, input: 8, panel: 11, card: 14 };

export const shadow = {
  panel: webOnly({ boxShadow: '0 1px 2px rgba(16,24,40,0.04)' }, { elevation: 1 }),
  raised: webOnly({ boxShadow: '0 1px 3px rgba(16,24,40,0.07)' }, { elevation: 2 }),
  drawer: webOnly({ boxShadow: '-10px 0 40px rgba(16,24,40,0.14)' }, { elevation: 8 }),
};

// Load the brand fonts on web. Native builds fall back to system fonts.
let fontsRequested = false;
export function loadWebFonts() {
  if (Platform.OS !== 'web' || fontsRequested || typeof document === 'undefined') return;
  fontsRequested = true;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href =
    'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700' +
    '&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap';
  document.head.appendChild(link);
}

export const BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'];

// Display form of a blood group: a true minus sign reads better than a hyphen.
export const bg = (group) => (group || '').replace('-', '−');

// Donor status vocabulary. Backend values -> how the dashboard shows them.
export const STATUS = {
  ringing:   { label: 'Calling',     tone: 'blue',  live: true },
  answered:  { label: 'Answered',    tone: 'blue',  live: true },
  no_answer: { label: 'No answer',   tone: 'muted' },
  picked_up: { label: 'Answered',    tone: 'muted' },
  accepted:  { label: 'Accepted',    tone: 'green', pill: true },
  en_route:  { label: 'En route',    tone: 'green', pill: true },
  completed: { label: 'En route',    tone: 'green', pill: true },
  donated:   { label: 'Donated',     tone: 'green', pill: true },
  declined:  { label: 'Declined',    tone: 'muted' },
};

export const toneColor = {
  blue: color.blue, green: color.green, amber: color.amber, red: color.red,
  violet: color.violet, muted: color.slate,
};
export const toneText = {
  blue: color.blueText, green: color.greenText, amber: color.amberText, red: color.redText,
  violet: color.violetText, muted: color.text2,
};
