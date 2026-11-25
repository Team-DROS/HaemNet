// Shown for any URL the dashboard does not know. Static hosts rewrite every
// path to index.html, so without this screen a mistyped link rendered a
// blank page.

import React, { useEffect } from 'react';
import { Platform, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { HaemNetMark } from '../components/Icons';
import { applyWebTheme, color, font, getSavedTheme, loadWebFonts, radius } from '../components/theme';
import { Button } from '../components/ui';

export default function NotFound() {
  const router = useRouter();
  useEffect(() => {
    loadWebFonts();
    applyWebTheme(getSavedTheme());
    if (Platform.OS === 'web' && typeof document !== 'undefined') {
      const previous = document.title;
      document.title = 'Page not found | HaemNet';
      return () => { document.title = previous; };
    }
    return undefined;
  }, []);

  return (
    <View style={s.root}>
      <View style={s.card} accessibilityRole="main">
        <HaemNetMark size={34} />
        <Text style={s.title} accessibilityRole="header" aria-level={1}>Page not found</Text>
        <Text style={s.body}>
          This address is not part of the HaemNet dashboard. Active requests and donor
          responses are on the Command Center.
        </Text>
        <Button onPress={() => router.replace('/')} accessibilityLabel="Go to the HaemNet dashboard">
          Go to the dashboard
        </Button>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16, backgroundColor: color.canvas },
  card: {
    width: '100%', maxWidth: 420, alignItems: 'flex-start', gap: 14, padding: 28,
    backgroundColor: color.surface, borderWidth: 1, borderColor: color.border, borderRadius: radius.card,
  },
  title: { fontFamily: font.display, fontSize: 24, fontWeight: '600', color: color.text },
  body: { fontFamily: font.body, fontSize: 15, lineHeight: 22, color: color.text2 },
});
