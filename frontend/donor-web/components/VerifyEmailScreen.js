// Landing page for the link in the verification email: /verify-email?token=...

import React, { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { API_URL } from './useDispatchStore';
import { color, font, radius } from './theme';
import { Button } from './ui';

export default function VerifyEmailScreen() {
  const { token } = useLocalSearchParams();
  const router = useRouter();
  const [state, setState] = useState({ status: 'working', message: '' });

  useEffect(() => {
    if (!token) return setState({ status: 'error', message: 'This link is missing its token. Open the link from your email again.' });
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/hospitals/verify-email`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Verification failed.');
        setState({ status: 'ok', message: '' });
      } catch (e) { setState({ status: 'error', message: e.message }); }
    })();
  }, [token]);

  return (
    <View style={s.root}>
      <View style={s.card}>
        {state.status === 'working' && <ActivityIndicator color={color.text} />}
        {state.status === 'ok' && (<>
          <Text style={s.h1}>Email verified</Text>
          <Text style={s.p}>Thank you. Sign in to upload your documents and track the review of your registration.</Text>
          <Button onPress={() => router.replace('/')}>Go to sign in</Button>
        </>)}
        {state.status === 'error' && (<>
          <Text style={s.h1}>Could not verify</Text>
          <Text style={s.p}>{state.message}</Text>
          <Button variant="secondary" onPress={() => router.replace('/')}>Go to sign in</Button>
        </>)}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: color.bg, alignItems: 'center', justifyContent: 'center', padding: 20 },
  card: { width: '100%', maxWidth: 440, backgroundColor: color.surface, borderWidth: 1, borderColor: color.border, borderRadius: radius.card, padding: 28, gap: 14 },
  h1: { fontFamily: font.display, fontSize: 22, fontWeight: '600', color: color.text },
  p: { fontFamily: font.body, fontSize: 14.5, lineHeight: 21, color: color.muted },
});
