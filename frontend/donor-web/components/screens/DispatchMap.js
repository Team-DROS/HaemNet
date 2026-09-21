// Dispatch Map: where the request is, who is within reach, and who is coming.
//
// Donor coordinates never leave the server (the dashboard only receives each
// donor's distance), so donors are shown by distance band rather than as
// pins on the map. The map itself shows the hospital's real location.

import React, { useEffect, useMemo, useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Map as MapIcon } from '../Icons';
import { bg, color, font, STATUS, toneColor, toneText } from '../theme';
import { EmptyState, formatElapsed, Label, LiveDot, Mono, Num, Panel, Pill, StatusCell } from '../ui';
import { summarize } from '../useDispatchStore';

const BANDS = [
  { key: 'b2', label: '0–2 km', max: 2 },
  { key: 'b5', label: '2–5 km', max: 5 },
  { key: 'b10', label: '5–10 km', max: 10.5 },
];

const GROUPS = [
  { key: 'confirmed', label: 'Confirmed', tone: 'green', match: (st) => ['accepted', 'en_route', 'completed', 'donated'].includes(st) },
  { key: 'contacting', label: 'Contacting', tone: 'blue', match: (st) => st === 'ringing' || st === 'answered' },
  { key: 'unavailable', label: 'Unavailable', tone: 'muted', match: (st) => st === 'no_answer' || st === 'declined' },
];

export default function DispatchMap({ store, compact }) {
  const { selected: em } = store;
  const [donorId, setDonorId] = useState(null);

  const donors = useMemo(
    () => (em ? Object.values(em.donors).sort((a, b) => (a.distance ?? 99) - (b.distance ?? 99)) : []),
    [em],
  );
  useEffect(() => {
    if (!donors.find((d) => d.id === donorId)) {
      const first = donors.find((d) => GROUPS[0].match(d.status)) || donors[0];
      setDonorId(first?.id || null);
    }
  }, [donors, donorId]);

  if (!em) {
    return (
      <View style={{ flex: 1, padding: 22 }}>
        <Panel style={{ flex: 1, justifyContent: 'center' }}>
          <EmptyState icon={<MapIcon size={26} color={color.faint} />} title="No request selected"
            body="Trigger an emergency from the Command Center to see its donor network here." />
        </Panel>
      </View>
    );
  }

  const donor = donors.find((d) => d.id === donorId);
  const location = em.address ? `${em.address}, ${store.profile.location || ''}` : store.profile.location || store.profile.name;

  const content = (
    <>
      <RequestColumn store={store} donors={donors} donorId={donorId} setDonorId={setDonorId} compact={compact} />
      <View style={[s.mapCol, compact && { height: 520 }]}>
        <HospitalMap query={location} coords={store.availability.data} />
        <MapOverlay em={em} store={store} donors={donors} />
      </View>
      <DonorDetail em={em} donor={donor} compact={compact} />
    </>
  );

  return compact ? (
    <ScrollView contentContainerStyle={{ gap: 0 }}>{content}</ScrollView>
  ) : (
    <View style={s.body}>{content}</View>
  );
}

// ── Left: request + donors by distance ───────────────────────────

function RequestColumn({ store, donors, donorId, setDonorId, compact }) {
  const em = store.selected;
  const sm = summarize(em);
  const open = store.ordered.filter((e) => !e.closed);

  return (
    <View style={[s.left, compact && { width: '100%', borderRightWidth: 0, borderBottomWidth: 1 }]}>
      <View style={{ padding: 16 }}>
        <Label>ACTIVE EMERGENCIES</Label>
        <View style={{ gap: 8, marginTop: 11 }}>
          {(open.length ? open : [em]).slice(0, 3).map((e) => {
            const active = e.id === em.id;
            const critical = e.urgency === 'critical' && !e.closed;
            const esm = summarize(e);
            return (
              <Pressable key={e.id} onPress={() => store.setSelectedId(e.id)} accessibilityRole="button"
                style={[s.emCard, active && (critical ? s.emCardCritical : s.emCardActive)]}>
                <View style={[s.row, { justifyContent: 'space-between' }]}>
                  <Text style={[s.emGroup, { color: critical ? color.red : color.amberText }]}>{bg(e.bloodGroup)}</Text>
                  <View style={[s.row, { gap: 6 }]}>
                    {!e.closed && <LiveDot tone={critical ? 'red' : 'amber'} size={6} />}
                    <Text style={[s.emUrgency, { color: critical ? color.redText : color.amberText }]}>{e.urgency.toUpperCase()}</Text>
                  </View>
                </View>
                <Text style={s.emMeta}>{e.units} unit{e.units > 1 ? 's' : ''} · elapsed {formatElapsed(store.now - e.createdAt)}</Text>
                <View style={[s.row, { gap: 14, marginTop: 8 }]}>
                  <Text style={[s.emStat, { color: color.blueText }]}>{esm.live} live</Text>
                  <Text style={[s.emStat, { color: color.greenText }]}>{esm.accepted} confirmed</Text>
                </View>
              </Pressable>
            );
          })}
        </View>
      </View>

      <View style={s.leftDivider} />
      <View style={[s.row, { justifyContent: 'space-between', paddingHorizontal: 16, paddingTop: 12, paddingBottom: 8 }]}>
        <Label>DONORS IN RANGE · {donors.length}</Label>
        <Text style={s.small}>{sm.accepted} confirmed</Text>
      </View>
      <ScrollView style={{ flex: 1, maxHeight: compact ? 320 : undefined }}>
        {donors.map((d) => {
          const meta = STATUS[d.status] || { tone: 'muted', label: d.status };
          const active = d.id === donorId;
          return (
            <Pressable key={d.id} onPress={() => setDonorId(d.id)} accessibilityRole="button"
              accessibilityState={{ selected: active }}
              style={({ hovered }) => [s.donorRow, active && { backgroundColor: color.selected }, hovered && !active && { backgroundColor: color.surface2 }]}>
              <LiveDot tone={meta.tone} size={8} pulse={!!meta.live} />
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={s.donorName} numberOfLines={1}>{d.name}</Text>
                <Text style={s.small}>{d.distance != null ? `${d.distance.toFixed(1)} km` : '—'} · {meta.label.toLowerCase()}</Text>
              </View>
              <Text style={[s.tag, { color: toneText[meta.tone] }]}>{meta.label.toUpperCase()}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

// ── Centre: real map of the hospital + distance bands ────────────

function HospitalMap({ query, coords }) {
  if (Platform.OS !== 'web') {
    return <View style={s.mapFallback}><Text style={s.small}>Map is available on the web dashboard.</Text></View>;
  }
  const q = coords?.lat ? `${coords.lat},${coords.lng}` : query || 'Chennai';
  const src = `https://maps.google.com/maps?q=${encodeURIComponent(q)}&t=m&z=13&ie=UTF8&iwloc=&output=embed`;
  return React.createElement('iframe', {
    title: 'Hospital location',
    src,
    style: { position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', border: 0, filter: 'saturate(0.55) contrast(0.96)' },
    loading: 'lazy',
    referrerPolicy: 'no-referrer-when-downgrade',
  });
}

function MapOverlay({ em, store, donors }) {
  const bands = BANDS.map((band, i) => {
    const min = i === 0 ? 0 : BANDS[i - 1].max;
    const inBand = donors.filter((d) => d.distance != null && d.distance >= min && d.distance < band.max);
    return { ...band, total: inBand.length, parts: GROUPS.map((g) => ({ ...g, n: inBand.filter((d) => g.match(d.status)).length })) };
  });
  const peak = Math.max(1, ...bands.map((b) => b.total));
  const sm = summarize(em);

  return (
    <>
      <View style={s.topOverlay} pointerEvents="box-none">
        <View style={s.hospitalCard}>
          <View style={s.hospitalMark}><Text style={s.hospitalPlus}>+</Text></View>
          <View style={{ minWidth: 0 }}>
            <Text style={s.hospitalName} numberOfLines={1}>{store.profile.name || 'Hospital'}</Text>
            <Text style={s.small} numberOfLines={1}>{em.address || store.profile.location || 'Requesting facility'} · 10 km search radius</Text>
          </View>
        </View>
        <View style={s.counts}>
          <CountCell n={sm.live} label="Contacting" tone="blue" />
          <CountCell n={sm.accepted} label="Confirmed" tone="green" />
          <CountCell n={donors.length} label="In range" />
        </View>
      </View>

      <View style={s.bandsCard}>
        <View style={[s.row, { justifyContent: 'space-between', marginBottom: 12 }]}>
          <Label>DONORS BY DISTANCE</Label>
          <View style={[s.row, { gap: 12 }]}>
            {GROUPS.map((g) => (
              <View key={g.key} style={[s.row, { gap: 6 }]}>
                <View style={[s.legendDot, { backgroundColor: toneColor[g.tone] }]} />
                <Text style={s.small}>{g.label}</Text>
              </View>
            ))}
          </View>
        </View>
        {bands.map((band) => (
          <View key={band.key} style={[s.row, { gap: 12, marginBottom: 9 }]}>
            <Text style={s.bandLabel}>{band.label}</Text>
            <View style={s.bandTrack}>
              {band.parts.map((p) => p.n > 0 && (
                <View key={p.key} style={{ width: `${(p.n / peak) * 100}%`, height: 12, backgroundColor: toneColor[p.tone], opacity: p.key === 'unavailable' ? 0.45 : 1 }} />
              ))}
            </View>
            <Text style={s.bandN}>{band.total}</Text>
          </View>
        ))}
        <Text style={[s.small, { marginTop: 4 }]}>
          Nearest confirmed donor: {(() => {
            const c = donors.find((d) => GROUPS[0].match(d.status));
            return c ? `${c.name}, ${c.distance?.toFixed(1)} km${c.eta != null ? `, ETA ${c.eta} min` : ''}` : 'none yet';
          })()}
        </Text>
      </View>
    </>
  );
}

function CountCell({ n, label, tone }) {
  return (
    <View style={s.countCell}>
      <Num size={16} tone={tone}>{n}</Num>
      <Text style={[s.small, { marginTop: 3 }]}>{label}</Text>
    </View>
  );
}

// ── Right: selected donor ────────────────────────────────────────

function DonorDetail({ em, donor, compact }) {
  if (!donor) {
    return (
      <View style={[s.right, compact && { width: '100%', borderLeftWidth: 0 }]}>
        <EmptyState title="Select a donor" body="Pick anyone from the list to see their status and call history." />
      </View>
    );
  }
  const meta = STATUS[donor.status] || { tone: 'muted', label: donor.status };
  const history = em.events.filter((ev) => ev.donorId === donor.id || (ev.donorIds || []).includes(donor.id)).slice(0, 8);

  return (
    <View style={[s.right, compact && { width: '100%', borderLeftWidth: 0 }]}>
      <View style={{ padding: 20 }}>
        <View style={[s.row, { justifyContent: 'space-between', alignItems: 'flex-start' }]}>
          <View style={{ flex: 1, minWidth: 0 }}>
            <Label>SELECTED DONOR</Label>
            <Text style={s.detailName} numberOfLines={1}>{donor.name}</Text>
            <Mono style={{ marginTop: 3 }}>{donor.id.slice(0, 8)}</Mono>
          </View>
          <Pill tone={meta.tone}>{meta.label.toUpperCase()}</Pill>
        </View>

        <View style={[s.row, { alignItems: 'flex-end', gap: 26, marginTop: 20 }]}>
          <View>
            <Text style={[s.detailGroup, { color: em.urgency === 'critical' ? color.red : color.text }]}>{bg(em.bloodGroup)}</Text>
            <Text style={[s.small, { marginTop: 6 }]}>Blood group</Text>
          </View>
          <View>
            <Num size={26}>{donor.distance != null ? `${donor.distance.toFixed(1)} km` : '—'}</Num>
            <Text style={[s.small, { marginTop: 6 }]}>Distance</Text>
          </View>
          <View>
            <Num size={26} tone={donor.eta != null ? 'green' : undefined}>{donor.eta != null ? `${donor.eta} min` : '—'}</Num>
            <Text style={[s.small, { marginTop: 6 }]}>ETA</Text>
          </View>
        </View>
      </View>

      <View style={s.stateBand}>
        <StatusCell status={donor.status} />
        <Text style={[s.small, { marginTop: 4 }]}>
          Last update {new Date(donor.updatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </Text>
      </View>

      <View style={{ padding: 20, gap: 11, borderBottomWidth: 1, borderBottomColor: color.borderSoft }}>
        <Fact label="Contact method" value={donor.status === 'en_route' && !history.some((h) => h.kind === 'call') ? 'App or AI voice' : 'AI voice call'} />
        <Fact label="Language" value={donor.language ? donor.language[0].toUpperCase() + donor.language.slice(1) : '—'} />
        <Fact label="Eligibility" value="Passed 56-day check" tone="green" />
        <Fact label="Matched to" value={`${bg(em.bloodGroup)} · ${em.units} unit${em.units > 1 ? 's' : ''}`} />
      </View>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 20 }}>
        <Label>CALL HISTORY</Label>
        <View style={{ marginTop: 14 }}>
          {history.length === 0 ? (
            <Text style={s.small}>Calling started for this donor; outcomes will appear here.</Text>
          ) : history.map((ev, i) => (
            <View key={ev.id} style={s.row}>
              <View style={{ alignSelf: 'stretch', flexDirection: 'row' }}>
                <Mono style={{ width: 40, textAlign: 'right', marginRight: 10 }}>
                  {new Date(ev.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </Mono>
                <View style={{ width: 12, alignItems: 'center' }}>
                  <View style={[s.histDot, { backgroundColor: toneColor[ev.tone] || color.disabled }]} />
                  {i < history.length - 1 && <View style={s.histLine} />}
                </View>
              </View>
              <View style={{ flex: 1, paddingLeft: 11, paddingBottom: 14 }}>
                <Text style={s.histTitle}>{ev.title}</Text>
                {ev.sub ? <Text style={[s.small, { marginTop: 2 }]}>{ev.sub}</Text> : null}
              </View>
            </View>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

function Fact({ label, value, tone }) {
  return (
    <View style={[s.row, { justifyContent: 'space-between' }]}>
      <Text style={s.factLabel}>{label}</Text>
      <Text style={[s.factValue, tone && { color: toneText[tone] }]}>{value}</Text>
    </View>
  );
}

const shadow = Platform.OS === 'web' ? { boxShadow: '0 1px 3px rgba(16,24,40,0.08)' } : { elevation: 2 };

const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  body: { flex: 1, flexDirection: 'row', minHeight: 0 },
  small: { fontFamily: font.body, fontSize: 11.5, color: color.muted },

  left: { width: 272, backgroundColor: color.surface, borderRightWidth: 1, borderRightColor: color.border },
  leftDivider: { height: 1, backgroundColor: color.borderSoft },
  emCard: { padding: 12, borderRadius: 9, borderWidth: 1, borderColor: color.border },
  emCardActive: { backgroundColor: color.selected, borderColor: '#D7E0EE' },
  emCardCritical: { backgroundColor: color.redBand, borderColor: color.redBorder },
  emGroup: { fontFamily: font.display, fontSize: 19, fontWeight: '700' },
  emUrgency: { fontFamily: font.body, fontSize: 10.5, fontWeight: '700', letterSpacing: 0.6 },
  emMeta: { fontFamily: font.body, fontSize: 11.5, color: color.text2, marginTop: 6 },
  emStat: { fontFamily: font.body, fontSize: 11.5, fontWeight: '600' },
  donorRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, paddingVertical: 10 },
  donorName: { fontFamily: font.body, fontSize: 12.5, fontWeight: '600', color: color.text },
  tag: { fontFamily: font.body, fontSize: 9.5, fontWeight: '600', letterSpacing: 0.4 },

  mapCol: { flex: 1, position: 'relative', backgroundColor: '#EDF0F4', minWidth: 0 },
  mapFallback: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  topOverlay: { position: 'absolute', top: 16, left: 16, right: 16, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 },
  hospitalCard: { flexDirection: 'row', alignItems: 'center', gap: 11, backgroundColor: color.surface, borderRadius: 10, borderWidth: 1, borderColor: color.border, paddingVertical: 10, paddingHorizontal: 13, maxWidth: 380, ...shadow },
  hospitalMark: { width: 30, height: 30, borderRadius: 8, backgroundColor: color.red, alignItems: 'center', justifyContent: 'center' },
  hospitalPlus: { color: '#FFFFFF', fontSize: 20, fontWeight: '700', lineHeight: 22 },
  hospitalName: { fontFamily: font.display, fontSize: 14, fontWeight: '600', color: color.text },
  counts: { flexDirection: 'row', backgroundColor: color.surface, borderRadius: 10, borderWidth: 1, borderColor: color.border, overflow: 'hidden', ...shadow },
  countCell: { paddingVertical: 9, paddingHorizontal: 15, alignItems: 'center', borderRightWidth: 1, borderRightColor: color.borderSoft },
  bandsCard: { position: 'absolute', left: 16, right: 16, bottom: 16, backgroundColor: color.surface, borderRadius: 11, borderWidth: 1, borderColor: color.border, padding: 16, maxWidth: 560, ...shadow },
  legendDot: { width: 9, height: 9, borderRadius: 5 },
  bandLabel: { fontFamily: font.body, fontSize: 12, color: color.text2, width: 56 },
  bandTrack: { flex: 1, flexDirection: 'row', height: 12, borderRadius: 3, overflow: 'hidden', backgroundColor: color.track },
  bandN: { fontFamily: font.display, fontSize: 13, fontWeight: '700', color: color.text, width: 24, textAlign: 'right' },

  right: { width: 336, backgroundColor: color.surface, borderLeftWidth: 1, borderLeftColor: color.border },
  detailName: { fontFamily: font.display, fontSize: 19, fontWeight: '600', color: color.text, marginTop: 7 },
  detailGroup: { fontFamily: font.display, fontSize: 36, fontWeight: '700', letterSpacing: -1, lineHeight: 38 },
  stateBand: { paddingHorizontal: 20, paddingVertical: 14, backgroundColor: color.surface2, borderTopWidth: 1, borderBottomWidth: 1, borderColor: color.borderSoft },
  factLabel: { fontFamily: font.body, fontSize: 12.5, color: color.text2 },
  factValue: { fontFamily: font.body, fontSize: 12.5, fontWeight: '600', color: color.text },
  histDot: { width: 9, height: 9, borderRadius: 5, marginTop: 3 },
  histLine: { flex: 1, width: 1.5, backgroundColor: color.borderSoft, marginVertical: 4 },
  histTitle: { fontFamily: font.body, fontSize: 12.5, fontWeight: '600', color: color.text },
});
