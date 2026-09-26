// Command Center: the live emergency response console.

import React, { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Check, Network, Plus } from '../Icons';
import { bg, color, font, radius } from '../theme';
import {
  Button, EmptyState, formatClock, formatDuration, formatElapsed, Label, LiveDot, Mono, Num, Panel,
  Segmented, StatusCell,
} from '../ui';
import { summarize } from '../useDispatchStore';

export default function CommandCenter({ store, compact, onNew }) {
  const { selected, ordered } = store;
  return (
    <View style={{ flex: 1 }}>
      <KpiStrip store={store} />
      {ordered.length === 0 || !selected ? (
        <EmptyCommand store={store} onNew={onNew} />
      ) : compact ? (
        <ScrollView contentContainerStyle={{ padding: 16, gap: 14 }}>
          <EmergencyPanel store={store} em={selected} />
          <DonorTable store={store} em={selected} fixedHeight={420} />
          <EmergencyList store={store} />
          <ActivityTimeline em={selected} fixedHeight={420} />
        </ScrollView>
      ) : (
        <View style={s.body}>
          <View style={{ flex: 1, gap: 14, minWidth: 0 }}>
            <EmergencyPanel store={store} em={selected} />
            <DonorTable store={store} em={selected} />
          </View>
          <View style={s.rail}>
            <EmergencyList store={store} />
            <ActivityTimeline em={selected} />
          </View>
        </View>
      )}
    </View>
  );
}

// ── KPI strip ────────────────────────────────────────────────────

function median(values) {
  if (!values.length) return null;
  const v = [...values].sort((a, b) => a - b);
  const mid = Math.floor(v.length / 2);
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
}

export function medianResponseMs(history) {
  return median(history.filter((h) => h.firstAcceptAt && h.createdAt).map((h) => h.firstAcceptAt - h.createdAt));
}

function KpiStrip({ store }) {
  const open = store.ordered.filter((e) => !e.closed);
  const totals = open.reduce((acc, em) => {
    const sm = summarize(em);
    acc.contacted += sm.contacted; acc.confirmed += sm.accepted; acc.enRoute += sm.enRoute; acc.live += sm.live;
    return acc;
  }, { contacted: 0, confirmed: 0, enRoute: 0, live: 0 });
  const critical = open.filter((e) => e.urgency === 'critical').length;
  const med = medianResponseMs(store.history);
  const dbOk = !!store.health?.dbOk;

  return (
    <View style={s.kpis}>
      <Kpi label="ACTIVE EMERGENCIES" value={open.length} tone={open.length ? 'red' : undefined}
        sub={open.length ? `${critical} critical · ${open.length - critical} other` : 'None open'} />
      <Kpi label="DONORS CONTACTED" value={totals.contacted}
        sub={totals.live ? `${totals.live} calls live now` : 'Across open requests'} />
      <Kpi label="DONORS CONFIRMED" value={totals.confirmed} tone={totals.confirmed ? 'green' : undefined}
        sub={`${totals.enRoute} en route`} />
      <Kpi label="MEDIAN RESPONSE" value={med == null ? '—' : formatDuration(med)}
        sub={med == null ? 'Needs a first acceptance' : 'Trigger to first acceptance'} />
      <View style={[s.kpi, s.kpiFixed, { flexBasis: 250 }]}>
        <Label>NETWORK STATUS</Label>
        <View style={[s.row, { marginTop: 9, gap: 9 }]}>
          <LiveDot tone={store.wsState === 'live' ? 'violet' : 'amber'} size={7} pulse={store.wsState === 'live'} />
          <Text style={s.kpiStatus}>{store.wsState === 'live' ? 'AI dispatch online' : 'Live feed offline'}</Text>
        </View>
        <Text style={s.kpiSub}>{dbOk ? 'Donor database connected' : store.health ? 'Donor database unreachable' : 'Checking donor database'}</Text>
      </View>
    </View>
  );
}

function Kpi({ label, value, sub, tone }) {
  return (
    <View style={s.kpi}>
      <Label>{label}</Label>
      <View style={[s.row, { alignItems: 'baseline', gap: 9, marginTop: 7 }]}>
        <Num size={27} tone={tone}>{value}</Num>
        <Text style={s.kpiSub} numberOfLines={1}>{sub}</Text>
      </View>
    </View>
  );
}

// ── Active emergency + lifecycle pipeline ────────────────────────

function EmergencyPanel({ store, em }) {
  const sm = summarize(em);
  const [busy, setBusy] = useState(false);
  const critical = em.urgency === 'critical';
  const elapsed = (em.closed ? em.closedAt || store.now : store.now) - em.createdAt;
  const tone = em.fulfilled ? 'green' : critical ? 'red' : em.urgency === 'urgent' ? 'amber' : 'blue';

  const close = async () => {
    setBusy(true);
    try { await store.closeEmergency(em.id); } catch (e) { /* surfaced by timeline */ }
    setBusy(false);
  };

  const band = em.fulfilled ? s.bandDone : critical && !em.closed ? s.bandCritical : s.bandNeutral;
  const edge = em.fulfilled ? color.green : critical && !em.closed ? color.red : color.border;

  return (
    <Panel>
      <View style={[s.band, band]}>
        <View style={{ width: 4, backgroundColor: edge }} />
        <View style={s.bandInner}>
          <View>
            <View style={[s.row, { gap: 8 }]}>
              {!em.closed && <LiveDot tone={tone} size={6} />}
              <Label tone={tone}>
                {em.fulfilled ? 'REQUEST FULFILLED' : em.closed ? 'REQUEST CLOSED' : `${em.urgency.toUpperCase()} REQUEST`}
              </Label>
            </View>
            <View style={[s.row, { alignItems: 'baseline', gap: 14, marginTop: 8 }]}>
              <Text style={[s.group, { color: critical && !em.closed ? color.red : color.text }]}>{bg(em.bloodGroup) || '—'}</Text>
              <Text style={s.units}>{em.units} unit{em.units > 1 ? 's' : ''}</Text>
            </View>
          </View>

          <View style={s.bandDivider} />

          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={s.place} numberOfLines={1}>
              {store.profile.name || 'Hospital'}{em.address ? ` · ${em.address}` : ''}
            </Text>
            <View style={[s.row, { gap: 12, marginTop: 7, flexWrap: 'wrap' }]}>
              <Text style={s.meta}>
                {em.closed ? 'Open for ' : 'Requested '}
                <Text style={s.metaStrong}>{formatElapsed(elapsed)}</Text>
                {em.closed ? '' : ' ago'}
              </Text>
              {em.patient ? <Text style={s.meta}>Patient <Text style={s.metaStrong}>{em.patient}</Text></Text> : null}
              <Mono>{em.id.slice(0, 8)}</Mono>
            </View>
          </View>

          <View style={[s.row, { gap: 28 }]}>
            <BigStat label="CONFIRMED" value={String(sm.accepted).padStart(2, '0')} tone={sm.accepted ? 'green' : undefined} />
            <BigStat label="EN ROUTE" value={String(sm.enRoute).padStart(2, '0')} tone={sm.enRoute ? 'green' : undefined} />
            <BigStat label="FIRST ARRIVAL" value={sm.nextEta != null ? `${sm.nextEta} min` : '—'} />
            {!em.closed && (
              <Button variant="secondary" onPress={close} disabled={busy} accessibilityLabel="Close this request">
                Close request
              </Button>
            )}
          </View>
        </View>
      </View>

      <Pipeline em={em} sm={sm} />
    </Panel>
  );
}

function BigStat({ label, value, tone }) {
  return (
    <View>
      <Label>{label}</Label>
      <Num size={24} tone={tone} style={{ marginTop: 5 }}>{value}</Num>
    </View>
  );
}

const STAGES = [
  { key: 'triggered', label: 'Triggered' },
  { key: 'matched', label: 'Matched' },
  { key: 'contacting', label: 'Contacting' },
  { key: 'answered', label: 'Answered' },
  { key: 'accepted', label: 'Accepted' },
  { key: 'en_route', label: 'En route' },
  { key: 'fulfilled', label: 'Fulfilled' },
];

// TRIGGER → MATCH → CONTACT → ANSWER → ACCEPT → EN ROUTE → FULFIL
export function Pipeline({ em, sm }) {
  const current = em.closed && !em.fulfilled ? -1 : sm.stage;
  const values = {
    triggered: { n: 1, sub: formatClock(em.createdAt) },
    matched: { n: em.matched, sub: 'within 10 km' },
    contacting: { n: sm.contacted, sub: sm.live ? `${sm.live} line${sm.live === 1 ? '' : 's'} live` : 'calls placed' },
    answered: { n: sm.answered, sub: sm.contacted ? `${Math.round((sm.answered / sm.contacted) * 100)}% pickup` : '—' },
    accepted: { n: sm.accepted, sub: sm.answered ? `${Math.round((sm.accepted / sm.answered) * 100)}% of answers` : '—' },
    en_route: { n: sm.enRoute, sub: sm.nextEta != null ? `first in ${sm.nextEta} min` : '—' },
    fulfilled: { n: `${sm.donated} / ${em.units}`, sub: em.fulfilled ? 'complete' : 'units donated' },
  };

  return (
    <View style={s.pipe}>
      <View style={[s.row, { justifyContent: 'space-between', marginBottom: 16 }]}>
        <Label>RESPONSE PIPELINE</Label>
        <Text style={s.kpiSub}>
          {em.fulfilled ? 'All units donated' : em.closed ? 'Closed before fulfilment' : `Stage ${Math.min(current + 1, 7)} of 7 · ${STAGES[Math.min(current, 6)].label.toLowerCase()}`}
        </Text>
      </View>
      <View style={s.row}>
        {STAGES.map((stage, i) => {
          const done = i < current || (em.fulfilled && i <= 6);
          const active = i === current && !em.fulfilled && !em.closed;
          const last = i === STAGES.length - 1;
          const v = values[stage.key];
          return (
            <View key={stage.key} style={{ flex: last ? 0 : 1, minWidth: last ? 110 : 0 }}>
              <View style={s.row}>
                <StageNode done={done} active={active} />
                {!last && (
                  <View style={s.pipeRail}>
                    <View style={[s.pipeRailFill, { width: done ? '100%' : active ? '55%' : '0%', backgroundColor: done ? color.green : color.blue, opacity: done ? 0.35 : 1 }]} />
                  </View>
                )}
              </View>
              <Text style={[s.stageLabel, active && { color: color.blueText, fontWeight: '700' }]}>{stage.label}</Text>
              <View style={[s.row, { alignItems: 'baseline', gap: 6, marginTop: 3 }]}>
                <Num size={19} tone={active ? 'blue' : stage.key === 'accepted' || stage.key === 'en_route' ? (v.n ? 'green' : undefined) : undefined}
                  style={!done && !active && i > current ? { color: color.faint } : null}>
                  {v.n}
                </Num>
              </View>
              <Text style={s.stageSub} numberOfLines={1}>{v.sub}</Text>
            </View>
          );
        })}
      </View>
    </View>
  );
}

function StageNode({ done, active }) {
  if (done) {
    return (
      <View style={[s.node, { backgroundColor: color.greenSurface }]}>
        <Check size={11} color={color.green} />
      </View>
    );
  }
  if (active) {
    return (
      <View style={{ width: 20, height: 20, alignItems: 'center', justifyContent: 'center' }}>
        <View style={{ position: 'absolute' }}><LiveDot tone="blue" size={20} /></View>
        <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: '#FFFFFF' }} />
      </View>
    );
  }
  return <View style={[s.node, { borderWidth: 2, borderColor: color.border }]} />;
}

// ── Donor response queue ─────────────────────────────────────────

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'live', label: 'In progress' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'failed', label: 'Unavailable' },
];

const ORDER = { donated: 0, en_route: 1, completed: 1, accepted: 2, answered: 3, ringing: 4, no_answer: 5, declined: 6 };

function DonorTable({ store, em, fixedHeight }) {
  const [filter, setFilter] = useState('all');
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState(null);

  const donors = useMemo(() => {
    const list = Object.values(em.donors);
    const keep = {
      all: () => true,
      live: (d) => d.status === 'ringing' || d.status === 'answered',
      confirmed: (d) => ['accepted', 'en_route', 'completed', 'donated'].includes(d.status),
      failed: (d) => d.status === 'no_answer' || d.status === 'declined',
    }[filter];
    return list.filter(keep).sort((a, b) =>
      (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9) || (a.distance ?? 99) - (b.distance ?? 99));
  }, [em.donors, filter]);

  const counts = useMemo(() => {
    const list = Object.values(em.donors);
    return {
      all: list.length,
      live: list.filter((d) => d.status === 'ringing' || d.status === 'answered').length,
      confirmed: list.filter((d) => ['accepted', 'en_route', 'completed', 'donated'].includes(d.status)).length,
      failed: list.filter((d) => d.status === 'no_answer' || d.status === 'declined').length,
    };
  }, [em.donors]);

  const donate = async (donorId) => {
    setBusyId(donorId); setError(null);
    try { await store.markDonated(em.id, donorId); } catch (e) { setError(e.message); }
    setBusyId(null);
  };

  return (
    <Panel style={[{ flex: fixedHeight ? undefined : 1 }, fixedHeight && { height: fixedHeight }]}>
      <View style={[s.row, s.tableHead]}>
        <View style={[s.row, { gap: 12 }]}>
          <Text style={s.panelTitle}>Donor response queue</Text>
          <Text style={s.kpiSub}>{em.matched} matched · ranked by status then distance</Text>
        </View>
        <Segmented
          value={filter}
          onChange={setFilter}
          options={FILTERS.map((f) => ({ ...f, label: `${f.label} ${counts[f.value]}` }))}
        />
      </View>
      {error ? <Text style={s.error}>{error}</Text> : null}
      <View style={[s.row, s.th]}>
        <Text style={[s.thText, { flex: 2.2 }]}>DONOR</Text>
        <Text style={[s.thText, { flex: 0.7 }]}>BLOOD</Text>
        <Text style={[s.thText, { flex: 0.9 }]}>DISTANCE</Text>
        <Text style={[s.thText, { flex: 1.4 }]}>CONTACT</Text>
        <Text style={[s.thText, { flex: 1.2 }]}>RESPONSE</Text>
        <Text style={[s.thText, { flex: 0.8, textAlign: 'right' }]}>ETA</Text>
        <Text style={[s.thText, { width: 118, textAlign: 'right' }]}> </Text>
      </View>
      <ScrollView style={{ flex: 1 }}>
        {donors.length === 0 ? (
          <EmptyState
            title={Object.keys(em.donors).length ? 'No donors in this view' : 'Placing calls'}
            body={Object.keys(em.donors).length ? 'Try another filter.' : 'Donor rows appear the moment the AI starts calling.'}
          />
        ) : donors.map((d) => (
          <DonorRow key={d.id} d={d} em={em} onDonate={donate} busy={busyId === d.id} />
        ))}
      </ScrollView>
    </Panel>
  );
}

function DonorRow({ d, em, onDonate, busy }) {
  const confirmed = ['accepted', 'en_route', 'completed', 'donated'].includes(d.status);
  const dim = d.status === 'no_answer' || d.status === 'declined';
  const canDonate = ['accepted', 'en_route', 'completed'].includes(d.status) && !em.closed;
  const contact = {
    ringing: 'ringing', answered: 'answered', no_answer: 'no_answer', declined: 'picked_up',
    accepted: 'picked_up', en_route: 'picked_up', completed: 'picked_up', donated: 'picked_up',
  }[d.status] || d.status;

  return (
    <View style={[s.row, s.tr, confirmed && { backgroundColor: '#FAFDFB' }]}>
      <View style={{ flex: 2.2, minWidth: 0 }}>
        <Text style={[s.donorName, dim && { color: color.text2 }]} numberOfLines={1}>{d.name}</Text>
        <Mono style={{ marginTop: 2 }}>{d.id.slice(0, 8)}{d.language ? ` · ${d.language}` : ''}</Mono>
      </View>
      <Text style={[s.cellGroup, { flex: 0.7 }, dim && { color: color.text2 }]}>{bg(em.bloodGroup)}</Text>
      <Text style={[s.cell, { flex: 0.9 }]}>{d.distance != null ? `${d.distance.toFixed(1)} km` : '—'}</Text>
      <View style={{ flex: 1.4 }}><StatusCell status={contact} /></View>
      <View style={{ flex: 1.2 }}>
        {confirmed || d.status === 'declined' ? (
          <StatusCell status={d.status} />
        ) : (
          <Text style={s.cellMuted}>{d.status === 'no_answer' ? 'Unreachable' : 'Awaiting answer'}</Text>
        )}
      </View>
      <Text style={[s.eta, { flex: 0.8 }, !(confirmed && d.eta != null) && { color: color.disabled, fontWeight: '400' }]}>
        {confirmed && d.status !== 'donated' && d.eta != null ? `${d.eta} min` : d.status === 'donated' ? 'Arrived' : '—'}
      </Text>
      <View style={{ width: 118, alignItems: 'flex-end' }}>
        {canDonate && (
          <Button variant="success" onPress={() => onDonate(d.id)} disabled={busy} style={{ paddingVertical: 6, paddingHorizontal: 10 }}
            textStyle={{ fontSize: 12 }} accessibilityLabel={`Mark ${d.name} as donated`}>
            {busy ? 'Saving…' : 'Mark donated'}
          </Button>
        )}
      </View>
    </View>
  );
}

// ── Right rail ───────────────────────────────────────────────────

function EmergencyList({ store }) {
  const list = store.ordered.slice(0, 5);
  return (
    <Panel style={{ flexShrink: 0 }}>
      <View style={[s.row, { justifyContent: 'space-between', paddingHorizontal: 16, paddingTop: 13, paddingBottom: 11 }]}>
        <Label>EMERGENCIES</Label>
        <Text style={s.kpiSub}>{store.ordered.filter((e) => !e.closed).length} open</Text>
      </View>
      {list.map((em) => {
        const sm = summarize(em);
        const active = em.id === store.selectedId;
        const critical = em.urgency === 'critical' && !em.closed;
        return (
          <Pressable
            key={em.id}
            onPress={() => store.setSelectedId(em.id)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            style={({ hovered }) => [s.emRow, active && (critical ? s.emActiveCritical : s.emActive), hovered && !active && { backgroundColor: color.surface2 }]}
          >
            <Text style={[s.emGroup, { color: em.fulfilled ? color.muted : critical ? color.red : em.closed ? color.muted : color.amberText }]}>
              {bg(em.bloodGroup) || '··'}
            </Text>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={[s.emTitle, em.closed && { color: color.text2 }]} numberOfLines={1}>
                {em.patient || em.address || `${em.units} unit request`}
              </Text>
              <Text style={s.emSub} numberOfLines={1}>
                {em.fulfilled ? `Fulfilled in ${formatDuration((em.closedAt || store.now) - em.createdAt)}`
                  : em.closed ? 'Closed'
                    : `${em.units} unit${em.units > 1 ? 's' : ''} · ${sm.accepted} confirmed · ${sm.live} live`}
              </Text>
            </View>
            {em.fulfilled ? <Check size={14} color={color.green} /> : !em.closed ? (
              <Text style={[s.emTime, critical && { color: color.redText }]}>{formatElapsed(store.now - em.createdAt)}</Text>
            ) : null}
          </Pressable>
        );
      })}
    </Panel>
  );
}

const TONE_DOT = { green: color.green, blue: color.blue, violet: color.violet, amber: color.amber, red: color.red, muted: color.disabled };

function ActivityTimeline({ em, fixedHeight }) {
  return (
    <Panel style={[{ flex: fixedHeight ? undefined : 1, minHeight: 0 }, fixedHeight && { height: fixedHeight }]}>
      <View style={[s.row, { justifyContent: 'space-between', paddingHorizontal: 16, paddingTop: 14, paddingBottom: 10 }]}>
        <View style={[s.row, { gap: 9 }]}>
          <LiveDot tone="violet" size={7} pulse={!em.closed} />
          <Text style={s.panelTitle}>AI activity</Text>
        </View>
        <Text style={s.kpiSub}>{em.closed ? 'Final' : 'Live'}</Text>
      </View>
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 16 }}>
        {em.events.length === 0 ? (
          <Text style={[s.kpiSub, { paddingVertical: 12 }]}>Events appear here as the AI works the request.</Text>
        ) : em.events.map((ev, i) => (
          <View key={ev.id} style={s.row}>
            <View style={{ alignSelf: 'stretch', flexDirection: 'row' }}>
              <Mono style={s.evTime}>{formatClock(ev.at)}</Mono>
              <View style={{ width: 14, alignItems: 'center' }}>
                <View style={[s.evDot, { backgroundColor: TONE_DOT[ev.tone] || color.disabled }]} />
                {i < em.events.length - 1 && <View style={s.evLine} />}
              </View>
            </View>
            <View style={{ flex: 1, minWidth: 0, paddingBottom: 16, paddingLeft: 12 }}>
              <View style={[s.row, { gap: 8, flexWrap: 'wrap' }]}>
                <Text style={[s.evTitle, ev.tone === 'green' && { color: color.greenText }, ev.tone === 'red' && { color: color.redText }, ev.tone === 'muted' && { color: color.text2 }]}>
                  {ev.title}
                </Text>
                {ev.channel ? <View style={s.channel}><Text style={s.channelText}>{ev.channel}</Text></View> : null}
              </View>
              {ev.sub ? <Text style={s.evSub}>{ev.sub}</Text> : null}
            </View>
          </View>
        ))}
      </ScrollView>
    </Panel>
  );
}

// ── Empty state ──────────────────────────────────────────────────

function EmptyCommand({ store, onNew }) {
  const a = store.availability;
  return (
    <View style={{ flex: 1, padding: 22 }}>
      <Panel style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
        <EmptyState
          icon={<View style={s.emptyIcon}><Network size={22} color={color.blue} /></View>}
          title="No active emergencies"
          body="When a request is triggered, HaemNet matches eligible donors within 10 km, calls them concurrently and streams every answer here in real time."
          action={
            <Button onPress={onNew} icon={<Plus size={14} color="#FFFFFF" />}>New emergency request</Button>
          }
        />
        {a.status === 'ready' && (
          <View style={s.availRow}>
            {Object.entries(a.data.groups).map(([g, n]) => (
              <View key={g} style={s.availCell}>
                <Text style={[s.availGroup, n === 0 && { color: color.red }]}>{bg(g)}</Text>
                <Text style={s.availN}>{n}</Text>
              </View>
            ))}
          </View>
        )}
        {a.status === 'ready' && (
          <Text style={[s.kpiSub, { marginTop: 10 }]}>
            Eligible donors ready within {a.data.radius_km} km right now · {a.data.total} total
          </Text>
        )}
        {a.status === 'error' && <Text style={[s.kpiSub, { marginTop: 14 }]}>{a.error}</Text>}
      </Panel>
    </View>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  body: { flex: 1, flexDirection: 'row', gap: 16, paddingHorizontal: 22, paddingTop: 16, paddingBottom: 18, minHeight: 0 },
  rail: { width: 348, gap: 14, minHeight: 0 },

  kpis: { flexDirection: 'row', paddingHorizontal: 22, paddingTop: 16, paddingBottom: 14, borderBottomWidth: 1, borderBottomColor: '#E9ECF2' },
  kpi: { flexGrow: 1, flexBasis: 0, paddingHorizontal: 22, borderRightWidth: 1, borderRightColor: '#E9ECF2', minWidth: 0 },
  kpiFixed: { flexGrow: 0, flexShrink: 0, borderRightWidth: 0 },
  kpiSub: { fontFamily: font.body, fontSize: 12, color: color.text2 },
  kpiStatus: { fontFamily: font.body, fontSize: 14, fontWeight: '600', color: color.text },

  band: { flexDirection: 'row', borderBottomWidth: 1 },
  bandCritical: { backgroundColor: color.redBand, borderBottomColor: '#F4E3E1' },
  bandDone: { backgroundColor: color.greenBand, borderBottomColor: '#D8EFE4' },
  bandNeutral: { backgroundColor: color.surface2, borderBottomColor: color.borderSoft },
  bandInner: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 28, paddingHorizontal: 22, paddingVertical: 18, flexWrap: 'wrap' },
  bandDivider: { width: 1, alignSelf: 'stretch', backgroundColor: '#EEDDDB' },
  group: { fontFamily: font.display, fontSize: 46, fontWeight: '700', letterSpacing: -1.4, lineHeight: 48 },
  units: { fontFamily: font.display, fontSize: 21, fontWeight: '600', color: color.text },
  place: { fontFamily: font.display, fontSize: 17, fontWeight: '600', color: color.text },
  meta: { fontFamily: font.body, fontSize: 12.5, color: color.text2 },
  metaStrong: { fontFamily: font.mono, color: color.text, fontWeight: '500' },

  pipe: { paddingHorizontal: 22, paddingTop: 18, paddingBottom: 20 },
  node: { width: 20, height: 20, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  pipeRail: { flex: 1, height: 2, backgroundColor: color.border, marginHorizontal: 6, overflow: 'hidden' },
  pipeRailFill: { height: 2 },
  stageLabel: { fontFamily: font.body, fontSize: 12, fontWeight: '600', color: color.text2, marginTop: 10 },
  stageSub: { fontFamily: font.body, fontSize: 11, color: color.muted, marginTop: 2 },

  panelTitle: { fontFamily: font.display, fontSize: 15, fontWeight: '600', color: color.text },
  tableHead: { justifyContent: 'space-between', paddingHorizontal: 18, paddingVertical: 12, flexWrap: 'wrap', gap: 10 },
  th: { paddingHorizontal: 18, paddingVertical: 9, gap: 14, backgroundColor: color.surface2, borderTopWidth: 1, borderBottomWidth: 1, borderColor: color.borderSoft },
  thText: { fontFamily: font.body, fontSize: 11, fontWeight: '600', color: color.muted, letterSpacing: 0.5 },
  tr: { paddingHorizontal: 18, paddingVertical: 11, gap: 14, borderBottomWidth: 1, borderBottomColor: color.divider, minHeight: 50 },
  donorName: { fontFamily: font.body, fontSize: 13.5, fontWeight: '600', color: color.text },
  cellGroup: { fontFamily: font.display, fontSize: 14, fontWeight: '600', color: color.text },
  cell: { fontFamily: font.body, fontSize: 13, color: color.text2 },
  cellMuted: { fontFamily: font.body, fontSize: 13, color: color.muted },
  eta: { fontFamily: font.display, fontSize: 15, fontWeight: '700', color: color.greenText, textAlign: 'right' },
  error: { fontFamily: font.body, fontSize: 12, color: color.redText, paddingHorizontal: 18, paddingBottom: 8 },

  emRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 11, borderTopWidth: 1, borderTopColor: color.divider },
  emActive: { backgroundColor: color.selected },
  emActiveCritical: { backgroundColor: color.redBand },
  emGroup: { fontFamily: font.display, fontSize: 17, fontWeight: '700', width: 34 },
  emTitle: { fontFamily: font.body, fontSize: 13, fontWeight: '600', color: color.text },
  emSub: { fontFamily: font.body, fontSize: 11.5, color: color.text2, marginTop: 2 },
  emTime: { fontFamily: font.mono, fontSize: 13, color: color.text2 },

  evTime: { width: 44, textAlign: 'right', fontSize: 11, paddingTop: 1, marginRight: 10 },
  evDot: { width: 9, height: 9, borderRadius: 5, marginTop: 4 },
  evLine: { flex: 1, width: 1.5, backgroundColor: color.borderSoft, marginVertical: 4 },
  evTitle: { fontFamily: font.body, fontSize: 13, fontWeight: '600', color: color.text },
  evSub: { fontFamily: font.body, fontSize: 11.5, color: color.muted, marginTop: 3 },
  channel: { backgroundColor: color.violetSurface, paddingHorizontal: 7, paddingVertical: 2, borderRadius: 5 },
  channelText: { fontFamily: font.body, fontSize: 10, fontWeight: '600', color: color.violetText, letterSpacing: 0.4 },

  emptyIcon: { width: 48, height: 48, borderRadius: 14, backgroundColor: color.blueSurface, alignItems: 'center', justifyContent: 'center' },
  availRow: { flexDirection: 'row', gap: 1, marginTop: 8, backgroundColor: color.borderSoft, borderRadius: radius.input, overflow: 'hidden', borderWidth: 1, borderColor: color.borderSoft },
  availCell: { backgroundColor: color.surface, paddingVertical: 10, paddingHorizontal: 16, alignItems: 'center' },
  availGroup: { fontFamily: font.display, fontSize: 14, fontWeight: '700', color: color.text },
  availN: { fontFamily: font.body, fontSize: 12, color: color.text2, marginTop: 2 },
});

