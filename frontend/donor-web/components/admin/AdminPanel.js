// HaemNet admin panel (route /admin): review hospital registrations, open the
// uploaded documents, approve, reject or suspend with a reason, and see the
// audit trail. Uses its own admin token, separate from hospital sessions.

import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { API_URL } from '../useDispatchStore';
import { color, font, radius, loadWebFonts } from '../theme';
import { Button } from '../ui';

const TOKEN_KEY = 'haemnet_admin_token';
const TABS = ['pending', 'approved', 'rejected', 'suspended'];
const KIND = { hfr_certificate: 'HFR certificate', establishment_registration: 'Clinical Establishments registration',
  blood_centre_licence: 'Blood centre licence', other: 'Other' };

export default function AdminPanel() {
  useEffect(loadWebFonts, []);
  const [token, setToken] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(TOKEN_KEY).then((t) => setToken(t)).catch(() => {}).finally(() => setReady(true));
  }, []);
  const signOut = useCallback(async () => { await AsyncStorage.removeItem(TOKEN_KEY).catch(() => {}); setToken(null); }, []);

  if (!ready) return <View style={s.center}><ActivityIndicator color={color.text} /></View>;
  if (!token) return <AdminLogin onToken={async (t) => { await AsyncStorage.setItem(TOKEN_KEY, t).catch(() => {}); setToken(t); }} />;
  return <Review token={token} onSignOut={signOut} />;
}

function useAdminApi(token, onSignOut) {
  return useCallback(async (path, { method = 'GET', body, raw } = {}) => {
    const res = await fetch(`${API_URL}${path}`, {
      method, headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401) { onSignOut(); throw new Error('Session expired. Sign in again.'); }
    if (raw) { if (!res.ok) throw new Error('Could not load the file'); return res.blob(); }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`);
    return data;
  }, [token, onSignOut]);
}

function AdminLogin({ onToken }) {
  const [form, setForm] = useState({ username: '', password: '' });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError(null); setBusy(true);
    try {
      const res = await fetch(`${API_URL}/api/admin/token`, {
        method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams(form).toString(),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Sign in failed');
      await onToken(data.access_token);
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  return (
    <View style={s.center}>
      <View style={s.loginCard}>
        <Text style={s.h1}>HaemNet admin</Text>
        <Text style={s.muted}>Authorised staff only.</Text>
        <TextInput style={s.input} placeholder="Username" placeholderTextColor={color.faint} value={form.username}
          onChangeText={(v) => setForm((f) => ({ ...f, username: v }))} autoCapitalize="none" accessibilityLabel="Username" />
        <TextInput style={s.input} placeholder="Password" placeholderTextColor={color.faint} value={form.password} secureTextEntry
          onChangeText={(v) => setForm((f) => ({ ...f, password: v }))} onSubmitEditing={submit} accessibilityLabel="Password" />
        {error ? <Text style={s.error}>{error}</Text> : null}
        <Button onPress={submit} disabled={busy || !form.username || !form.password}>{busy ? 'Signing in…' : 'Sign in'}</Button>
      </View>
    </View>
  );
}

function Review({ token, onSignOut }) {
  const api = useAdminApi(token, onSignOut);
  const [tab, setTab] = useState('pending');
  const [list, setList] = useState({ loading: true, rows: [], error: null });
  const [selected, setSelected] = useState(null);

  const load = useCallback(async () => {
    setList((l) => ({ ...l, loading: true, error: null }));
    try {
      const data = await api(`/api/admin/hospitals?status=${tab}`);
      setList({ loading: false, rows: data.hospitals, error: null });
    } catch (e) { setList({ loading: false, rows: [], error: e.message }); }
  }, [api, tab]);
  useEffect(() => { load(); }, [load]);

  return (
    <View style={s.root}>
      <View style={s.top}>
        <Text style={s.h1}>Hospital review</Text>
        <Button variant="secondary" onPress={onSignOut}>Sign out</Button>
      </View>
      <View style={s.tabs}>
        {TABS.map((t) => (
          <Pressable key={t} onPress={() => { setTab(t); setSelected(null); }} accessibilityRole="button"
            accessibilityState={{ selected: tab === t }} style={[s.tab, tab === t && s.tabOn]}>
            <Text style={[s.tabText, tab === t && { color: color.blueText }]}>{t[0].toUpperCase() + t.slice(1)}</Text>
          </Pressable>
        ))}
      </View>
      <View style={s.split}>
        <ScrollView style={s.listPane}>
          {list.loading ? <ActivityIndicator color={color.muted} style={{ margin: 20 }} />
            : list.error ? <Text style={[s.error, { padding: 14 }]}>{list.error}</Text>
            : list.rows.length === 0 ? <Text style={[s.muted, { padding: 14 }]}>No {tab} hospitals.</Text>
            : list.rows.map((h) => (
              <Pressable key={h.id} onPress={() => setSelected(h.id)} accessibilityRole="button"
                style={[s.item, selected === h.id && s.itemOn]}>
                <Text style={s.itemName}>{h.name}</Text>
                <Text style={s.muted}>{h.id} · {h.email_verified ? 'email verified' : 'email not verified'} · {h.documents.length} doc{h.documents.length === 1 ? '' : 's'}</Text>
              </Pressable>
            ))}
        </ScrollView>
        <ScrollView style={s.detailPane} contentContainerStyle={{ padding: 20 }}>
          {selected ? <Detail key={selected} id={selected} api={api} onChanged={() => { setSelected(null); load(); }} />
            : <Text style={s.muted}>Select a hospital to review.</Text>}
        </ScrollView>
      </View>
    </View>
  );
}

function Detail({ id, api, onChanged }) {
  const [h, setH] = useState(null);
  const [error, setError] = useState(null);
  const [reason, setReason] = useState('');
  const [confirm, setConfirm] = useState(null); // action awaiting confirmation
  const [busy, setBusy] = useState(false);

  useEffect(() => { api(`/api/admin/hospitals/${id}`).then(setH).catch((e) => setError(e.message)); }, [id, api]);

  const openDoc = async (doc) => {
    try {
      const blob = await api(`/api/admin/hospitals/${id}/documents/${doc.id}`, { raw: true });
      window.open(URL.createObjectURL(blob), '_blank', 'noopener');
    } catch (e) { setError(e.message); }
  };

  const decide = async () => {
    setBusy(true); setError(null);
    try {
      await api(`/api/admin/hospitals/${id}/decision`, { method: 'POST', body: { action: confirm, reason: reason.trim() } });
      onChanged();
    } catch (e) { setError(e.message); setConfirm(null); }
    setBusy(false);
  };

  if (!h) return error ? <Text style={s.error}>{error}</Text> : <ActivityIndicator color={color.muted} />;
  const needsReason = confirm === 'reject' || confirm === 'suspend';
  const actions = { pending: ['approve', 'reject'], rejected: ['approve'], approved: ['suspend'], suspended: ['reinstate'] }[h.status] || [];

  return (
    <View style={{ gap: 14 }}>
      <Text style={s.h2}>{h.name}</Text>
      <Fact label="Hospital ID" value={h.id} />
      <Fact label="Status" value={h.status} />
      <Fact label="Address" value={h.location} />
      <Fact label="Phone" value={h.phone} />
      <Fact label="Official email" value={`${h.official_email || '-'} (${h.email_verified ? 'verified' : 'NOT verified'})`} />
      <Fact label="Contact person" value={h.contact_person} />
      <Fact label="HFR ID" value={h.hfr_id} />
      <Fact label="Registration number" value={h.registration_number} />
      <Fact label="Blood centre licence" value={h.blood_centre_licence} />
      {h.decision_reason ? <Fact label="Last reason" value={h.decision_reason} /> : null}

      <Text style={s.h3}>Documents</Text>
      {h.documents.length === 0 ? <Text style={s.muted}>None uploaded.</Text> : h.documents.map((d) => (
        <Pressable key={d.id} onPress={() => openDoc(d)} accessibilityRole="link" style={s.doc}>
          <Text style={s.docText}>{KIND[d.kind] || d.kind}: {d.filename}</Text>
          <Text style={s.muted}>{Math.round(d.size / 1024)} KB · open</Text>
        </Pressable>
      ))}

      {error ? <Text style={s.error}>{error}</Text> : null}

      {confirm ? (
        <View style={s.confirm}>
          <Text style={s.itemName}>{confirm[0].toUpperCase() + confirm.slice(1)} {h.name}?</Text>
          {needsReason ? (
            <TextInput style={[s.input, { minHeight: 70 }]} multiline placeholder="Reason (sent to the hospital)" placeholderTextColor={color.faint}
              value={reason} onChangeText={setReason} accessibilityLabel="Reason" />
          ) : <Text style={s.muted}>The hospital will be emailed.</Text>}
          <View style={s.rowGap}>
            <Button variant="secondary" onPress={() => setConfirm(null)}>Cancel</Button>
            <Button variant={confirm === 'approve' || confirm === 'reinstate' ? 'primary' : 'danger'} onPress={decide}
              disabled={busy || (needsReason && !reason.trim())}>{busy ? 'Saving…' : `Confirm ${confirm}`}</Button>
          </View>
        </View>
      ) : (
        <View style={s.rowGap}>
          {actions.map((a) => (
            <Button key={a} variant={a === 'reject' || a === 'suspend' ? 'danger' : 'primary'} onPress={() => { setReason(''); setConfirm(a); }}>
              {a[0].toUpperCase() + a.slice(1)}
            </Button>
          ))}
        </View>
      )}

      <Text style={s.h3}>Audit trail</Text>
      {h.audit.map((e, i) => (
        <Text key={i} style={s.muted}>{e.at.slice(0, 16).replace('T', ' ')} · {e.actor} · {e.action}{e.reason ? `: ${e.reason}` : ''}</Text>
      ))}
    </View>
  );
}

function Fact({ label, value }) {
  return (
    <View style={s.fact}>
      <Text style={s.factLabel}>{label}</Text>
      <Text style={s.factValue}>{value || '-'}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: color.bg },
  center: { flex: 1, backgroundColor: color.bg, alignItems: 'center', justifyContent: 'center', padding: 20 },
  loginCard: { width: '100%', maxWidth: 380, backgroundColor: color.surface, borderWidth: 1, borderColor: color.border, borderRadius: radius.card, padding: 24, gap: 12 },
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 16, borderBottomWidth: 1, borderBottomColor: color.border },
  tabs: { flexDirection: 'row', gap: 8, padding: 12, flexWrap: 'wrap' },
  tab: { paddingVertical: 7, paddingHorizontal: 14, borderRadius: radius.chip, borderWidth: 1, borderColor: color.border },
  tabOn: { backgroundColor: color.surface2, borderColor: color.blue },
  tabText: { fontFamily: font.body, fontSize: 13.5, color: color.text2 },
  split: { flex: 1, flexDirection: 'row', flexWrap: 'wrap' },
  listPane: { flexBasis: 320, flexGrow: 1, maxHeight: '100%', borderRightWidth: 1, borderRightColor: color.border },
  detailPane: { flexBasis: 420, flexGrow: 3 },
  item: { padding: 14, borderBottomWidth: 1, borderBottomColor: color.border },
  itemOn: { backgroundColor: color.surface2 },
  itemName: { fontFamily: font.body, fontSize: 14.5, fontWeight: '600', color: color.text },
  h1: { fontFamily: font.display, fontSize: 22, fontWeight: '600', color: color.text },
  h2: { fontFamily: font.display, fontSize: 20, fontWeight: '600', color: color.text },
  h3: { fontFamily: font.display, fontSize: 15, fontWeight: '600', color: color.text, marginTop: 8 },
  muted: { fontFamily: font.body, fontSize: 13, color: color.muted, lineHeight: 19 },
  error: { fontFamily: font.body, fontSize: 13.5, color: color.redText },
  input: { borderWidth: 1, borderColor: color.border, borderRadius: radius.input, padding: 11, fontFamily: font.body, fontSize: 14, color: color.text, backgroundColor: color.surface },
  fact: { flexDirection: 'row', gap: 12 },
  factLabel: { width: 150, fontFamily: font.body, fontSize: 13, color: color.muted },
  factValue: { flex: 1, fontFamily: font.body, fontSize: 14, color: color.text },
  doc: { borderWidth: 1, borderColor: color.border, borderRadius: radius.input, padding: 10 },
  docText: { fontFamily: font.body, fontSize: 14, color: color.blueText },
  confirm: { borderWidth: 1, borderColor: color.border, borderRadius: radius.panel, padding: 14, gap: 10, backgroundColor: color.surface2 },
  rowGap: { flexDirection: 'row', gap: 10, flexWrap: 'wrap' },
});
