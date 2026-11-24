// Shown instead of the dashboard until the hospital is approved. Walks the
// hospital through verifying its email, uploading licence documents and
// waiting for review, and explains rejection or suspension.

import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Check, HaemNetMark } from '../Icons';
import { color, font, radius } from '../theme';
import { Button } from '../ui';

const KINDS = [
  { value: 'hfr_certificate', label: 'HFR (ABDM) certificate' },
  { value: 'establishment_registration', label: 'Clinical Establishments registration' },
  { value: 'blood_centre_licence', label: 'Blood centre licence' },
  { value: 'other', label: 'Other proof' },
];
const MAX_MB = 5;
const TYPES = ['application/pdf', 'image/jpeg', 'image/png'];

function pickFile() {
  return new Promise((resolve) => {
    if (typeof document === 'undefined') return resolve(null);
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/pdf,image/jpeg,image/png';
    input.onchange = () => resolve(input.files && input.files[0] ? input.files[0] : null);
    input.click();
  });
}

export default function PendingReview({ store }) {
  const p = store.profile;
  const [kind, setKind] = useState('hfr_certificate');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null); // { tone, text }
  const status = p.status || 'pending';
  const docs = p.documents || [];

  // Keep the status fresh so approval appears without a manual reload.
  useEffect(() => {
    store.refreshProfile().catch(() => {});
    const t = setInterval(() => store.refreshProfile().catch(() => {}), 20000);
    return () => clearInterval(t);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const upload = async () => {
    setMsg(null);
    const file = await pickFile();
    if (!file) return;
    if (file.size > MAX_MB * 1024 * 1024) return setMsg({ tone: 'red', text: `That file is larger than ${MAX_MB} MB.` });
    if (!TYPES.includes(file.type)) return setMsg({ tone: 'red', text: 'Upload a PDF, JPG or PNG file.' });
    setBusy(true);
    try {
      await store.uploadDocument(kind, file);
      setMsg({ tone: 'green', text: `${file.name} uploaded.` });
    } catch (e) { setMsg({ tone: 'red', text: e.message }); }
    setBusy(false);
  };

  const resend = async () => {
    setMsg(null);
    try {
      const r = await store.resendVerification();
      setMsg(r.sent ? { tone: 'green', text: `Verification email sent to ${p.official_email}.` }
        : { tone: 'amber', text: r.detail || 'The email could not be sent right now. Try again later.' });
    } catch (e) { setMsg({ tone: 'red', text: e.message }); }
  };

  const heading = { pending: 'Your registration is under review', rejected: 'Your registration was not approved',
    suspended: 'Your account is suspended', approved: 'Approved' }[status];
  const emailDone = p.email_verified !== false;

  return (
    <ScrollView style={s.root} contentContainerStyle={s.body}>
      <View style={s.card}>
        <View style={s.row}>
          <HaemNetMark size={26} color={color.text} accent={color.red} />
          <Text style={s.brand}>HaemNet</Text>
          <View style={{ flex: 1 }} />
          <Button variant="secondary" onPress={store.logout}>Sign out</Button>
        </View>

        <Text style={s.h1}>{heading}</Text>
        <Text style={s.lede}>
          {status === 'pending' && `${p.name} (${p.id}) cannot send blood requests until our team approves it. This usually takes one to two working days.`}
          {status === 'rejected' && 'Please fix the issue below, upload new documents and write to us to be reviewed again.'}
          {status === 'suspended' && 'Requests are paused for this hospital. Contact HaemNet support if you think this is a mistake.'}
        </Text>

        {(status === 'rejected' || status === 'suspended') && p.decision_reason ? (
          <View style={[s.banner, { backgroundColor: color.redSurface }]}>
            <Text style={[s.bannerText, { color: color.redText }]}>Reason: {p.decision_reason}</Text>
          </View>
        ) : null}

        {status === 'pending' && (
          <View style={{ marginTop: 20 }}>
            <Step done={emailDone} title="Verify your official email"
              note={emailDone ? p.official_email : `We sent a link to ${p.official_email}. It expires in 48 hours.`}
              action={!emailDone ? <Button variant="secondary" onPress={resend}>Resend email</Button> : null} />
            <Step done={docs.length > 0} title="Upload your registration documents"
              note="ABDM Health Facility Registry certificate, state Clinical Establishments registration, and a blood centre licence if you store blood." />
            <Step done={false} title="Wait for review" note="We email you when a decision is made." last />
          </View>
        )}

        {status !== 'suspended' && (
          <View style={{ marginTop: 22 }}>
            <Text style={s.section}>Documents</Text>
            {docs.length === 0 ? <Text style={s.muted}>No documents uploaded yet.</Text> : docs.map((d) => (
              <View key={d.id} style={s.docRow}>
                <Check size={14} color={color.green} />
                <Text style={s.docName} numberOfLines={1}>{d.filename}</Text>
                <Text style={s.muted}>{(KINDS.find((k) => k.value === d.kind) || {}).label || d.kind}</Text>
              </View>
            ))}
            <View style={[s.row, { flexWrap: 'wrap', marginTop: 12, gap: 8 }]}>
              {KINDS.map((k) => (
                <Pressable key={k.value} onPress={() => setKind(k.value)} accessibilityRole="button"
                  accessibilityState={{ selected: kind === k.value }}
                  style={[s.chip, kind === k.value && s.chipOn]}>
                  <Text style={[s.chipText, kind === k.value && { color: color.blueText }]}>{k.label}</Text>
                </Pressable>
              ))}
            </View>
            <View style={{ marginTop: 12, alignSelf: 'flex-start' }}>
              <Button onPress={upload} disabled={busy}
                icon={busy ? <ActivityIndicator color="#FFFFFF" size="small" /> : null}>
                {busy ? 'Uploading…' : 'Choose file (PDF, JPG, PNG, up to 5 MB)'}
              </Button>
            </View>
          </View>
        )}

        {msg ? (
          <View style={[s.banner, { backgroundColor: msg.tone === 'green' ? color.greenSurface : msg.tone === 'amber' ? color.amberSurface : color.redSurface }]}>
            <Text style={[s.bannerText, { color: msg.tone === 'green' ? color.greenText : msg.tone === 'amber' ? color.amberText : color.redText }]}>{msg.text}</Text>
          </View>
        ) : null}
      </View>
    </ScrollView>
  );
}

function Step({ done, title, note, action, last }) {
  return (
    <View style={[s.step, !last && s.stepLine]}>
      <View style={[s.dot, done && { backgroundColor: color.green, borderColor: color.green }]}>
        {done ? <Check size={12} color="#FFFFFF" /> : null}
      </View>
      <View style={{ flex: 1 }}>
        <Text style={s.stepTitle}>{title}</Text>
        <Text style={s.muted}>{note}</Text>
      </View>
      {action}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: color.bg },
  body: { padding: 20, alignItems: 'center' },
  card: { width: '100%', maxWidth: 640, backgroundColor: color.surface, borderWidth: 1, borderColor: color.border, borderRadius: radius.card, padding: 24 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  brand: { fontFamily: font.display, fontSize: 18, fontWeight: '600', color: color.text },
  h1: { fontFamily: font.display, fontSize: 24, fontWeight: '600', color: color.text, marginTop: 22 },
  lede: { fontFamily: font.body, fontSize: 14.5, lineHeight: 21, color: color.muted, marginTop: 8 },
  section: { fontFamily: font.display, fontSize: 15, fontWeight: '600', color: color.text, marginBottom: 8 },
  muted: { fontFamily: font.body, fontSize: 13, color: color.muted, lineHeight: 19 },
  banner: { padding: 12, borderRadius: radius.input, marginTop: 14 },
  bannerText: { fontFamily: font.body, fontSize: 13.5, lineHeight: 19 },
  step: { flexDirection: 'row', gap: 12, alignItems: 'flex-start', paddingBottom: 16 },
  stepLine: { borderLeftWidth: 0 },
  stepTitle: { fontFamily: font.body, fontSize: 14.5, fontWeight: '600', color: color.text },
  dot: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: color.border, alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  docRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 6 },
  docName: { fontFamily: font.body, fontSize: 13.5, color: color.text, flexShrink: 1 },
  chip: { borderWidth: 1, borderColor: color.border, borderRadius: radius.chip, paddingVertical: 6, paddingHorizontal: 10 },
  chipOn: { borderColor: color.blue, backgroundColor: color.surface2 },
  chipText: { fontFamily: font.body, fontSize: 12.5, color: color.text2 },
});
