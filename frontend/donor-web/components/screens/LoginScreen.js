// Hospital sign-in and registration, with a quiet network visual.

import React, { useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, useWindowDimensions, View } from 'react-native';
import Svg, { Circle, Line } from 'react-native-svg';
import { Check, HaemNetMark, Hospital, Lock, Mic, Navigation, Network, Phone, MapPin } from '../Icons';
import { color, font, radius } from '../theme';
import { Button } from '../ui';

export default function LoginScreen({ store }) {
  const { width } = useWindowDimensions();
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ id: '', password: '', name: '', location: '', phone: '+91 ' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    setError(null); setSuccess(null);
    if (mode === 'login') {
      if (!form.id.trim() || !form.password) return setError('Enter your hospital ID and password.');
      setBusy(true);
      try { await store.login(form.id, form.password); } catch (e) {
        setError(e.status === 401 ? 'Hospital ID or password is incorrect.' : `Could not sign in: ${e.message}`);
      }
      setBusy(false);
    } else {
      if (!form.name.trim() || !form.location.trim() || form.phone.trim().length < 6 || form.password.length < 6) {
        return setError('Fill in every field. Passwords need at least 6 characters.');
      }
      setBusy(true);
      try {
        const id = await store.register({ name: form.name.trim(), location: form.location.trim(), phone: form.phone.trim(), password: form.password });
        setForm((f) => ({ ...f, id }));
        setMode('login');
        setSuccess(`Registered. Your hospital ID is ${id}. Keep it safe; you sign in with it.`);
      } catch (e) { setError(`Registration failed: ${e.message}`); }
      setBusy(false);
    }
  };

  const showVisual = width >= 980;

  return (
    <View style={s.root}>
      <View style={[s.left, !showVisual && { width: '100%', maxWidth: 560, alignSelf: 'center' }]}>
        <View style={[s.row, { gap: 11 }]}>
          <HaemNetMark size={30} />
          <Text style={s.brand}>HaemNet</Text>
        </View>

        <View style={{ flex: 1, justifyContent: 'center' }}>
          <Text style={s.h1}>{mode === 'login' ? 'Sign in to the hospital network' : 'Register your hospital'}</Text>
          <Text style={s.lede}>
            {mode === 'login'
              ? 'For credentialed blood bank staff. Every dispatch, call and acceptance is recorded against your hospital ID.'
              : 'Your hospital ID is issued when you register. The location is used to find donors near you, so use the full address.'}
          </Text>

          {store.notice ? <Banner tone="amber">{store.notice}</Banner> : null}
          {success ? <Banner tone="green">{success}</Banner> : null}

          {mode === 'register' && (
            <>
              <Field label="Hospital name" icon={<Hospital size={16} color={color.faint} />} value={form.name} onChangeText={set('name')} placeholder="Apollo Hospital" />
              <Field label="Full address" icon={<MapPin size={16} color={color.faint} />} value={form.location} onChangeText={set('location')} placeholder="21 Greams Lane, Chennai 600006" />
              <Field label="Blood bank in-charge phone" icon={<Phone size={16} color={color.faint} />} value={form.phone}
                onChangeText={(t) => set('phone')(t.replace(/[^0-9+ ]/g, ''))} placeholder="+91 98765 43210" keyboardType="phone-pad" />
            </>
          )}
          {mode === 'login' && (
            <Field label="Hospital ID" icon={<Hospital size={16} color={color.faint} />} value={form.id}
              onChangeText={(t) => set('id')(t.toUpperCase())} placeholder="HOSP-1001" autoCapitalize="characters" mono
              right={/^HOSP-\w+$/.test(form.id) ? <Check size={13} color={color.green} /> : null} />
          )}
          <Field label={mode === 'login' ? 'Password' : 'Create a password'} icon={<Lock size={16} color={color.faint} />}
            value={form.password} onChangeText={set('password')} placeholder="••••••••" secureTextEntry onSubmitEditing={submit} />

          {error ? <Text style={s.error}>{error}</Text> : null}

          <Button onPress={submit} disabled={busy} style={{ paddingVertical: 14, marginTop: 8 }} textStyle={{ fontSize: 14.5 }}
            icon={busy ? <ActivityIndicator color="#FFFFFF" size="small" /> : null}>
            {mode === 'login' ? 'Sign in' : 'Register hospital'}
          </Button>

          <Pressable onPress={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null); setSuccess(null); }}
            accessibilityRole="button" style={{ marginTop: 22, alignSelf: 'center' }}>
            <Text style={s.switch}>
              {mode === 'login' ? 'New facility? ' : 'Already registered? '}
              <Text style={s.switchLink}>{mode === 'login' ? 'Register a hospital' : 'Sign in'}</Text>
            </Text>
          </Pressable>
        </View>

        <Text style={s.footer}>HaemNet · emergency blood response</Text>
      </View>

      {showVisual && <NetworkVisual />}
    </View>
  );
}

function Field({ label, icon, right, mono, ...input }) {
  return (
    <View style={{ marginBottom: 16 }}>
      <Text style={s.fieldLabel}>{label}</Text>
      <View style={s.field}>
        {icon}
        <TextInput {...input} placeholderTextColor={color.faint}
          style={[s.input, mono && { fontFamily: font.mono }]} accessibilityLabel={label} />
        {right}
      </View>
    </View>
  );
}

function Banner({ tone, children }) {
  const bg = tone === 'green' ? color.greenSurface : color.amberSurface;
  const fg = tone === 'green' ? color.greenText : color.amberText;
  return <View style={[s.banner, { backgroundColor: bg }]}><Text style={[s.bannerText, { color: fg }]}>{children}</Text></View>;
}

// Decorative network: a hub, a few hospitals and a scatter of donors.
function NetworkVisual() {
  const nodes = useMemo(() => {
    let seed = 11;
    const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    return Array.from({ length: 64 }, (_, i) => {
      const a = rnd() * Math.PI * 2;
      const r = 90 + rnd() * 250;
      return { x: 400 + Math.cos(a) * r, y: 360 + Math.sin(a) * r * 0.85, near: r < 170, green: i % 11 === 0 };
    });
  }, []);
  const hospitals = [[250, 230], [570, 250], [270, 500], [560, 490]];

  return (
    <View style={s.right}>
      <Svg width="100%" height="100%" viewBox="0 0 800 720" preserveAspectRatio="xMidYMid slice" style={{ position: 'absolute' }}>
        {[120, 220, 320].map((r) => (
          <Circle key={r} cx="400" cy="360" r={r} fill="none" stroke="#E7EBF2" strokeWidth="1" strokeDasharray="3 8" />
        ))}
        {hospitals.map(([x, y], i) => (
          <Line key={i} x1="400" y1="360" x2={x} y2={y} stroke={i === 2 ? '#BFE0D2' : '#C9D6EB'} strokeWidth="1.2" strokeDasharray="4 7" />
        ))}
        {nodes.map((n, i) => (
          <Circle key={i} cx={n.x} cy={n.y} r={n.near ? 3.2 : 2.6} fill={n.near ? color.blue : n.green ? color.green : '#CBD5E3'} opacity={n.near ? 0.85 : 0.9} />
        ))}
        {hospitals.map(([x, y], i) => (
          <Circle key={`h${i}`} cx={x} cy={y} r="6" fill={i === 2 ? color.green : color.blue} stroke="#F7F9FC" strokeWidth="2" />
        ))}
        <Circle cx="400" cy="360" r="30" fill="#FFFFFF" stroke="#E4E8EF" />
      </Svg>
      <View style={s.hub}><HaemNetMark size={24} /></View>

      <View style={s.props}>
        <Prop icon={<Network size={16} color={color.violet} />} title="Match in one query"
          body="Blood group, distance and the 56-day cooldown resolved together in the donor graph." />
        <Prop icon={<Mic size={16} color={color.blue} />} title="Call everyone at once"
          body="AI voice calls every eligible donor concurrently, in English, Hindi or Tamil." />
        <Prop icon={<Navigation size={16} color={color.green} />} title="Track every answer live"
          body="Pickups, acceptances and ETAs stream to your console the moment they happen." />
      </View>
    </View>
  );
}

function Prop({ icon, title, body }) {
  return (
    <View style={s.prop}>
      <View style={s.propIcon}>{icon}</View>
      <View style={{ flex: 1 }}>
        <Text style={s.propTitle}>{title}</Text>
        <Text style={s.propBody}>{body}</Text>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, flexDirection: 'row', backgroundColor: color.surface, minHeight: '100%' },
  row: { flexDirection: 'row', alignItems: 'center' },
  left: { width: 580, paddingHorizontal: 64, paddingVertical: 44 },
  brand: { fontFamily: font.display, fontSize: 19, fontWeight: '700', color: color.text, letterSpacing: -0.4 },
  h1: { fontFamily: font.display, fontSize: 29, fontWeight: '600', color: color.text, letterSpacing: -0.6 },
  lede: { fontFamily: font.body, fontSize: 14, color: color.text2, lineHeight: 22, marginTop: 8, marginBottom: 28, maxWidth: 420 },
  fieldLabel: { fontFamily: font.body, fontSize: 12.5, fontWeight: '600', color: color.text, marginBottom: 8 },
  field: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 14, borderRadius: radius.input + 1, borderWidth: 1, borderColor: color.border, backgroundColor: color.surface },
  input: { flex: 1, paddingVertical: 13, fontFamily: font.body, fontSize: 14, color: color.text, outlineStyle: 'none' },
  error: { fontFamily: font.body, fontSize: 13, color: color.redText, marginBottom: 6 },
  banner: { borderRadius: 9, paddingHorizontal: 14, paddingVertical: 11, marginBottom: 18 },
  bannerText: { fontFamily: font.body, fontSize: 13, lineHeight: 19 },
  switch: { fontFamily: font.body, fontSize: 13.5, color: color.text2 },
  switchLink: { color: color.blue, fontWeight: '600' },
  footer: { fontFamily: font.body, fontSize: 12, color: color.muted },

  right: { flex: 1, backgroundColor: '#F7F9FC', borderLeftWidth: 1, borderLeftColor: color.borderSoft, overflow: 'hidden', justifyContent: 'flex-end' },
  hub: { position: 'absolute', left: '50%', top: '50%', marginLeft: -12, marginTop: -12 },
  props: { margin: 48, backgroundColor: color.surface, borderRadius: 12, borderWidth: 1, borderColor: color.border, paddingVertical: 6 },
  prop: { flexDirection: 'row', gap: 14, paddingHorizontal: 18, paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: color.divider },
  propIcon: { width: 32, height: 32, borderRadius: 9, backgroundColor: color.surface2, alignItems: 'center', justifyContent: 'center' },
  propTitle: { fontFamily: font.display, fontSize: 14, fontWeight: '600', color: color.text },
  propBody: { fontFamily: font.body, fontSize: 12.5, color: color.text2, marginTop: 3, lineHeight: 18 },
});
