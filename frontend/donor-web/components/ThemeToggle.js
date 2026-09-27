import React from 'react';
import { Platform, Pressable, StyleSheet, Text } from 'react-native';
import { color, font } from './theme';

export default function ThemeToggle({ theme, onToggle }) {
  if (Platform.OS !== 'web') return null;
  const next = theme === 'dark' ? 'light' : 'dark';
  return (
    <Pressable
      onPress={onToggle}
      accessibilityRole="button"
      accessibilityLabel={`Switch to ${next} theme`}
      style={s.button}
    >
      <Text style={s.text}>{theme === 'dark' ? '☀ Light theme' : '☾ Dark theme'}</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  button: { paddingHorizontal: 11, paddingVertical: 7, borderRadius: 7, borderWidth: 1, borderColor: color.border, backgroundColor: color.surface2 },
  text: { fontFamily: font.body, fontSize: 12, fontWeight: '600', color: color.text2 },
});
