// "New emergency request" side drawer. Replaces the form that used to sit
// permanently on the dashboard.

import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Activity, Network, X } from '../Icons';
import { bg, BLOOD_GROUPS, color, font, radius, shadow } from '../theme';
import { Button } from '../ui';

const URGENCY = [
  { value: 'routine', label: 'Routine' },
  { value: 'urgent', label: 'Urgent' },
  { value: 'critical', label: 'Critical' },
];

export default function NewRequestDrawer({ visible, onClose, store, onCreated }) {
  const [form, setForm] = useState({ patient: '', bloodGroup: 'O-', units: 1, urgency: 'critical', address: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [warning, setWarning] = useState(null);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    if (visible) { setError(null); setWarning(null); if (store.availability.status !== 'ready') store.refreshAvailability(); }
  }, [visible]); // eslint-disable-line react-hooks/exhaustive-deps

  const available = store.availability.data?.groups?.[form.bloodGroup];

  const submit = async () => {
    setError(null); setWarning(null);
    if (!form.address.trim()) return setError('Add the ward or delivery location so donors know where to go.');
    setBusy(true);
    try {
      const res = await store.triggerDispatch({ ...form, address: form.address.trim(), patient: form.patient.trim() });
      if (!res.matched) {
        setWarning(res.message || `No eligible ${bg(form.bloodGroup)} donors within 10 km right now.`);
      } else {
        setForm((f) => ({ ...f, patient: '' }));
        onCreated(res);
      }
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={s.scrim}>
        <Pressable style={{ flex: 1 }} onPress={onClose} accessibilityLabel="Close drawer" />
        <View style={[s.drawer, shadow.drawer]} accessibilityViewIsModal>
          <View style={s.head}>
            <View style={{ flex: 1 }}>
              <Text style={s.title}>New emergency request</Text>
              <Text style={s.sub}>Matching starts the moment you trigger it.</Text>
            </View>
            <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close" style={s.close}>
              <X size={14} color={color.text2} />
            </Pressable>
          </View>

          <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 24 }}>
            <Text style={s.label}>Blood group</Text>
            <View style={s.groups}>
              {BLOOD_GROUPS.map((g) => {
                const active = form.bloodGroup === g;
                return (
                  <Pressable key={g} onPress={() => set('bloodGroup')(g)} accessibilityRole="button" accessibilityState={{ selected: active }}
                    style={[s.groupBtn, active && s.groupActive]}>
                    <Text style={[s.groupText, active && { color: color.redText, fontWeight: '700' }]}>{bg(g)}</Text>
                  </Pressable>
                );
              })}
            </View>

            <View style={{ flexDirection: 'row', gap: 14, marginBottom: 20 }}>
              <View style={{ flex: 1 }}>
                <Text style={s.label}>Units required</Text>
                <View style={s.stepper}>
                  <Pressable onPress={() => set('units')(Math.max(1, form.units - 1))} style={s.stepBtn} accessibilityLabel="Fewer units">
                    <Text style={s.stepText}>−</Text>
                  </Pressable>
                  <Text style={s.stepValue}>{form.units}</Text>
                  <Pressable onPress={() => set('units')(Math.min(20, form.units + 1))} style={s.stepBtn} accessibilityLabel="More units">
                    <Text style={s.stepText}>+</Text>
                  </Pressable>
                </View>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.label}>Patient reference</Text>
                <TextInput value={form.patient} onChangeText={set('patient')} placeholder="PT-8841 or name"
                  placeholderTextColor={color.faint} style={s.input} accessibilityLabel="Patient reference" />
              </View>
            </View>

            <Text style={s.label}>Urgency</Text>
            <View style={{ flexDirection: 'row', gap: 8, marginBottom: 20 }}>
              {URGENCY.map((u) => {
                const active = form.urgency === u.value;
                const critical = u.value === 'critical';
                return (
                  <Pressable key={u.value} onPress={() => set('urgency')(u.value)} accessibilityRole="button" accessibilityState={{ selected: active }}
                    style={[s.urgBtn, active && (critical ? s.urgCritical : s.urgActive)]}>
                    <Text style={[s.urgText, active && { fontWeight: '700', color: critical ? color.redText : color.text }]}>{u.label}</Text>
                  </Pressable>
                );
              })}
            </View>

            <Text style={s.label}>Ward or delivery location</Text>
            <TextInput value={form.address} onChangeText={set('address')} placeholder="Trauma Bay 2, Block A"
              placeholderTextColor={color.faint} style={[s.input, { marginBottom: 22 }]} accessibilityLabel="Ward or delivery location" />

            <View style={s.preflight}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 11 }}>
                <Network size={14} color={color.violet} />
                <Text style={s.preTitle}>Pre-flight estimate</Text>
              </View>
              {store.availability.status === 'ready' ? (
                <>
                  <PreRow label={`Eligible ${bg(form.bloodGroup)} donors within ${store.availability.data.radius_km} km`}
                    value={String(available ?? 0)} tone={available ? undefined : 'red'} />
                  <PreRow label="Rule applied" value="Blood group · distance · 56-day cooldown" small />
                  {available === 0 && (
                    <Text style={[s.preNote, { color: color.redText }]}>No eligible donors of this group nearby. The request will return no matches.</Text>
                  )}
                </>
              ) : store.availability.status === 'error' ? (
                <Text style={s.preNote}>{store.availability.error}</Text>
              ) : (
                <ActivityIndicator color={color.muted} />
              )}
            </View>

            {warning ? <Text style={[s.msg, { color: color.amberText, backgroundColor: color.amberSurface }]}>{warning}</Text> : null}
            {error ? <Text style={[s.msg, { color: color.redText, backgroundColor: color.redSurface }]}>{error}</Text> : null}
          </ScrollView>

          <View style={s.foot}>
            <Button variant="secondary" onPress={onClose} style={{ flex: 1, paddingVertical: 13 }}>Cancel</Button>
            <Button variant="danger" onPress={submit} disabled={busy} style={{ flex: 2, paddingVertical: 13 }}
              icon={busy ? <ActivityIndicator color="#FFFFFF" size="small" /> : <Activity size={15} color="#FFFFFF" />}>
              {busy ? 'Matching donors…' : 'Trigger dispatch'}
            </Button>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function PreRow({ label, value, tone, small }) {
  return (
    <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 7, gap: 12 }}>
      <Text style={s.preLabel}>{label}</Text>
      <Text style={[small ? s.preSmall : s.preValue, tone === 'red' && { color: color.redText }]}>{value}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  scrim: { flex: 1, flexDirection: 'row', backgroundColor: 'rgba(15,26,43,0.28)' },
  drawer: { width: 460, maxWidth: '100%', backgroundColor: color.surface },
  head: { flexDirection: 'row', alignItems: 'flex-start', padding: 24, paddingBottom: 20, borderBottomWidth: 1, borderBottomColor: color.borderSoft },
  title: { fontFamily: font.display, fontSize: 19, fontWeight: '600', color: color.text },
  sub: { fontFamily: font.body, fontSize: 12.5, color: color.text2, marginTop: 5 },
  close: { width: 32, height: 32, borderRadius: 8, backgroundColor: color.canvas, borderWidth: 1, borderColor: color.border, alignItems: 'center', justifyContent: 'center' },
  label: { fontFamily: font.body, fontSize: 12, fontWeight: '600', color: color.text2, marginBottom: 9 },
  groups: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 20 },
  groupBtn: { width: '22.8%', alignItems: 'center', paddingVertical: 10, borderRadius: radius.input, borderWidth: 1, borderColor: color.border },
  groupActive: { borderColor: color.red, borderWidth: 1.5, backgroundColor: color.redSurface },
  groupText: { fontFamily: font.display, fontSize: 13, fontWeight: '600', color: color.text2 },
  stepper: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderColor: color.border, borderRadius: radius.input, overflow: 'hidden' },
  stepBtn: { width: 40, height: 42, alignItems: 'center', justifyContent: 'center', backgroundColor: color.surface2 },
  stepText: { fontSize: 16, color: color.text2 },
  stepValue: { flex: 1, textAlign: 'center', fontFamily: font.display, fontSize: 16, fontWeight: '700', color: color.text },
  input: { borderWidth: 1, borderColor: color.border, borderRadius: radius.input, paddingHorizontal: 14, paddingVertical: 12, fontFamily: font.body, fontSize: 13.5, color: color.text, outlineStyle: 'none' },
  urgBtn: { flex: 1, alignItems: 'center', paddingVertical: 11, borderRadius: radius.input, borderWidth: 1, borderColor: color.border },
  urgActive: { borderColor: color.text, borderWidth: 1.5, backgroundColor: color.surface2 },
  urgCritical: { borderColor: color.red, borderWidth: 1.5, backgroundColor: color.redSurface },
  urgText: { fontFamily: font.body, fontSize: 13, color: color.text2 },
  preflight: { padding: 16, borderRadius: 10, backgroundColor: color.surface2, borderWidth: 1, borderColor: color.borderSoft },
  preTitle: { fontFamily: font.body, fontSize: 12.5, fontWeight: '600', color: color.violetText },
  preLabel: { flex: 1, fontFamily: font.body, fontSize: 12.5, color: color.text2 },
  preValue: { fontFamily: font.display, fontSize: 14, fontWeight: '600', color: color.text },
  preSmall: { fontFamily: font.body, fontSize: 12, color: color.text2 },
  preNote: { fontFamily: font.body, fontSize: 12, color: color.text2, marginTop: 4, lineHeight: 17 },
  msg: { fontFamily: font.body, fontSize: 13, marginTop: 16, padding: 12, borderRadius: 8, lineHeight: 19 },
  foot: { flexDirection: 'row', gap: 10, padding: 16, paddingHorizontal: 24, borderTopWidth: 1, borderTopColor: color.borderSoft },
});
