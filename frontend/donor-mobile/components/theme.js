// HaemNet design tokens for the donor app. Mirrors donor-web/components/theme.js
// and design/tokens.json. Light-first: red is reserved for live emergencies and
// destructive actions; navy is the primary action colour.

import { Platform } from 'react-native';

export const light = {
  canvas: '#F5F7FA',
  surface: '#FFFFFF',
  surface2: '#F8FAFC',
  track: '#EEF1F5',

  border: '#E4E8EF',
  borderSoft: '#EDF0F5',
  divider: '#F1F3F7',

  text: '#0F1A2B',
  text2: '#58637A',
  muted: '#8B95A7',
  faint: '#AEB6C4',

  red: '#D92D20', redText: '#B42318', redSurface: '#FEF3F2', redBorder: '#F4D9D6',
  green: '#0E9B6C', greenText: '#08734F', greenSurface: '#E7F6EF', greenBorder: '#BFE5D3',
  blue: '#2E5FEA', blueText: '#1E46B8', blueSurface: '#EEF3FF',
  amber: '#E49412', amberText: '#A96206', amberSurface: '#FFF8EB', amberBorder: '#F5DFB5',
};

export const dark = {
  canvas: '#111927', surface: '#172234', surface2: '#1D2B3E', track: '#27354A',
  border: '#324156', borderSoft: '#2B394E', divider: '#2B394E',
  text: '#F4F7FB', text2: '#B8C4D5', muted: '#8C9BAF', faint: '#71829B',
  red: '#F0645A', redText: '#FFAAA3', redSurface: '#3B252B', redBorder: '#684048',
  green: '#31C493', greenText: '#71E0B5', greenSurface: '#183B37', greenBorder: '#2E6254',
  blue: '#789BFF', blueText: '#A7BEFF', blueSurface: '#263755',
  amber: '#EAB35B', amberText: '#F2C77C', amberSurface: '#403528', amberBorder: '#71593A',
};

export const palette = (theme) => theme === 'dark' ? dark : light;

export const mono = Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' });

export const radius = { chip: 8, input: 10, card: 14 };

export const shadow = Platform.select({
  ios: { shadowColor: '#101828', shadowOpacity: 0.05, shadowRadius: 3, shadowOffset: { width: 0, height: 1 } },
  android: { elevation: 1 },
  default: {},
});

// Display form of a blood group: a true minus sign reads better than a hyphen.
export const bg = (group) => (group || '').replace('-', '−');
