// Staff accounts for this hospital. Visible to the owner and staff admins.

import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { color, font, radius } from '../theme';
import { Button } from '../ui';

const ROLES = [{ value: 'staff', label: 'Staff' }, { value: 'admin', label: 'Admin' }];

export default function TeamScreen({ store }) {
  const [state, setState] = useState({ loading: true, rows: [], error: null });
  const [form, setForm] = useState({ name: '', email: '', role: 'staff', password: '' });
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirmId, setConfirmId] = useState(null);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  const load = useCallback(async () => {
    try { setState({ loading: false, rows: await store.listStaff(), error: null }); }
    catch (e) { setState({ loading: false, rows: [], error: e.message }); }
  }, [store]);
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const add = async () => {
    setMsg(null);
    if (!form.name.trim() || !/^\S+@\S+\.\S+$/.test(form.email.trim())) return setMsg({ bad: true, text: 'Enter a name and a valid email.' });
    if (form.password.length < 8) return setMsg({ bad: true, text: 'The password needs at least 8 characters.' });
    setBusy(true);
    try {
      await store.addStaff({ ...form, name: form.name.trim(), email: form.email.trim() });
      setForm({ name: '', email: '', role: 'staff', password: '' });
      setMsg({ text: 'Staff account created. Share the password with them privately.' });
      await load();
    } catch (e) { setMsg({ bad: true, text: e.message }); }
    setBusy(false);
  };

  const remove = async (id) => {
    try { await store.removeStaff(id); setConfirmId(null); await load(); }
    catch (e) { setMsg({ bad: true, text: e.message }); }
  };

  return (
    <ScrollView style={{ flex: 1 }} contentContainerStyle={s.body}>
      <View style={s.panel}>
        <Text style={s.h}>Staff accounts</Text>
        <Text style={s.muted}>Staff sign in with the hospital ID, their own email and password. Admins can manage this list. Removing someone signs them out immediately.</Text>
        {state.loading ? <ActivityIndicator color={color.muted} style={{ marginTop: 16 }} />
          : state.error ? <Text style={s.error}>{state.error}</Text>
          : state.rows.length === 0 ? <Text style={[s.muted, { marginTop: 14 }]}>No staff accounts yet. The hospital owner login always works.</Text>
          : state.rows.map((m) => (
            <View key={m.id} style={s.row}>
              <View style={{ flex: 1 }}>
                <Text style={s.name}>{m.name} <Text style={s.role}>{m.role}</Text></Text>
                <Text style={s.muted}>{m.email}</Text>
              </View>
              {confirmId === m.id ? (
                <View style={s.actions}>
                  <Button variant="secondary" onPress={() => setConfirmId(null)}>Keep</Button>
                  <Button variant="danger" onPress={() => remove(m.id)}>Remove</Button>
                </View>
              ) : <Button variant="secondary" onPress={() => setConfirmId(m.id)} accessibilityLabel={`Remove ${m.name}`}>Remove</Button>}
            </View>
          ))}
      </View>

      <View style={s.panel}>
        <Text style={s.h}>Add a staff member</Text>
        <TextInput style={s.input} placeholder="Full name" placeholderTextColor={color.faint} value={form.name} onChangeText={set('name')} accessibilityLabel="Full name" />
        <TextInput style={s.input} placeholder="Email" placeholderTextColor={color.faint} value={form.email} onChangeText={set('email')}
          autoCapitalize="none" keyboardType="email-address" accessibilityLabel="Email" />
        <TextInput style={s.input} placeholder="Temporary password (8+ characters)" placeholderTextColor={color.faint} value={form.password}
          onChangeText={set('password')} secureTextEntry accessibilityLabel="Temporary password" />
        <View style={s.actions}>
          {ROLES.map((r) => (
            <Pressable key={r.value} onPress={() => set('role')(r.value)} accessibilityRole="button" accessibilityState={{ selected: form.role === r.value }}
              style={[s.chip, form.role === r.value && s.chipOn]}>
              <Text style={[s.chipText, form.role === r.value && { color: color.blueText }]}>{r.label}</Text>
            </Pressable>
          ))}
        </View>
        {msg ? <Text style={msg.bad ? s.error : s.ok}>{msg.text}</Text> : null}
        <View style={{ alignSelf: 'flex-start' }}>
          <Button onPress={add} disabled={busy}>{busy ? 'Creating…' : 'Create account'}</Button>
        </View>
      </View>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  body: { padding: 20, gap: 16, maxWidth: 720, width: '100%' },
  panel: { backgroundColor: color.surface, borderWidth: 1, borderColor: color.border, borderRadius: radius.panel, padding: 18, gap: 10 },
  h: { fontFamily: font.display, fontSize: 17, fontWeight: '600', color: color.text },
  muted: { fontFamily: font.body, fontSize: 13, color: color.muted, lineHeight: 19 },
  name: { fontFamily: font.body, fontSize: 14.5, fontWeight: '600', color: color.text },
  role: { fontSize: 12, color: color.muted, fontWeight: '400' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 8, borderTopWidth: 1, borderTopColor: color.border },
  actions: { flexDirection: 'row', gap: 8 },
  input: { borderWidth: 1, borderColor: color.border, borderRadius: radius.input, padding: 11, fontFamily: font.body, fontSize: 14, color: color.text, backgroundColor: color.surface },
  chip: { borderWidth: 1, borderColor: color.border, borderRadius: radius.chip, paddingVertical: 6, paddingHorizontal: 14 },
  chipOn: { borderColor: color.blue, backgroundColor: color.surface2 },
  chipText: { fontFamily: font.body, fontSize: 13, color: color.text2 },
  error: { fontFamily: font.body, fontSize: 13.5, color: color.redText },
  ok: { fontFamily: font.body, fontSize: 13.5, color: color.greenText },
});
