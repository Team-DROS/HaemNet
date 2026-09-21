// Network Intelligence: decisions a blood bank can act on.
//
// Availability comes from the server (eligible donors per group right now).
// Everything else is computed from this hospital's dispatches as recorded
// on the server (GET /api/dispatches/history), so every staff browser sees
// the same numbers and nothing here is a demo figure.

import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Alert as AlertIcon, Chart } from '../Icons';
import { bg, BLOOD_GROUPS, color, font } from '../theme';
import { EmptyState, formatDuration, Label, LiveDot, Num, Panel, Pill, Segmented } from '../ui';
import { medianResponseMs } from './CommandCenter';

const DAY = 24 * 3600 * 1000;
const GROUP_ORDER = ['O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-'];

function percentile(values, p) {
  if (!values.length) return null;
  const v = [...values].sort((a, b) => a - b);
  return v[Math.min(v.length - 1, Math.floor((p / 100) * v.length))];
}

export default function NetworkIntelligence({ store, compact }) {
  const [range, setRange] = useState(30);
  const now = store.now;
  // Pull the hospital's recorded history from the server whenever the range grows.
  useEffect(() => { store.refreshHistory(Math.max(range, 30)); }, [range]); // eslint-disable-line react-hooks/exhaustive-deps
  const history = useMemo(
    () => store.history.filter((h) => now - h.createdAt <= range * DAY),
    [store.history, range, now],
  );

  const kpi = useMemo(() => {
    const done = history.filter((h) => h.status !== 'active');
    const fulfilled = done.filter((h) => h.status === 'fulfilled').length;
    return {
      requests: history.length,
      fulfilment: done.length ? (fulfilled / done.length) * 100 : null,
      fulfilled, done: done.length,
      median: medianResponseMs(history),
      avgContacted: history.length ? history.reduce((a, h) => a + (h.contacted || 0), 0) / history.length : null,
      donations: history.reduce((a, h) => a + (h.donated || 0), 0),
      critical: store.ordered.filter((e) => !e.closed && e.urgency === 'critical').length,
    };
  }, [history, store.ordered]);

  const body = (
    <>
      <View style={[s.split, compact && { flexDirection: 'column' }]}>
        <VolumeChart history={history} range={range} now={now} />
        <View style={compact ? s.hDivider : s.vDivider} />
        <Funnel history={history} />
      </View>
      <View style={[s.split, compact && { flexDirection: 'column' }]}>
        <Availability store={store} history={history} range={range} />
        <View style={compact ? s.hDivider : s.vDivider} />
        <ResponseTimes history={history} />
      </View>
      <HistoryTable history={store.history} now={now} />
    </>
  );

  return (
    <View style={{ flex: 1 }}>
      <View style={s.kpis}>
        <Kpi label="REQUESTS" value={kpi.requests} sub={`last ${range} days`} />
        <Kpi label="FULFILMENT RATE" tone={kpi.fulfilment != null ? 'green' : undefined}
          value={kpi.fulfilment != null ? `${kpi.fulfilment.toFixed(1)}%` : '—'}
          sub={kpi.done ? `${kpi.fulfilled} of ${kpi.done} closed` : 'no closed requests'} />
        <Kpi label="MEDIAN RESPONSE" value={kpi.median != null ? formatDuration(kpi.median) : '—'} sub="to first acceptance" />
        <Kpi label="DONORS PER REQUEST" value={kpi.avgContacted != null ? kpi.avgContacted.toFixed(1) : "—"} sub="contacted on average" />
        <Kpi label="DONATIONS" value={kpi.donations} sub="units logged" />
        <View style={[s.kpi, { borderRightWidth: 0, flexGrow: 0, flexShrink: 0, flexBasis: 220 }]}>
          <Label tone="red">UNRESOLVED CRITICAL</Label>
          <View style={[s.row, { alignItems: 'baseline', gap: 9, marginTop: 7 }]}>
            <Num size={28} tone={kpi.critical ? 'red' : undefined}>{kpi.critical}</Num>
            <Text style={s.sub}>{kpi.critical ? 'open right now' : 'none open'}</Text>
          </View>
        </View>
        <Segmented style={{ alignSelf: 'center', marginLeft: 12 }} value={range} onChange={setRange}
          options={[{ value: 7, label: '7 days' }, { value: 30, label: '30 days' }, { value: 90, label: '90 days' }]} />
      </View>
      <ScrollView contentContainerStyle={{ padding: 22, gap: 16 }}>{body}</ScrollView>
    </View>
  );
}

function Kpi({ label, value, sub, tone }) {
  return (
    <View style={s.kpi}>
      <Label>{label}</Label>
      <View style={{ marginTop: 7 }}>
        <Num size={28} tone={tone}>{value}</Num>
        {sub ? <Text style={[s.sub, { marginTop: 3 }]} numberOfLines={2}>{sub}</Text> : null}
      </View>
    </View>
  );
}

function Section({ title, sub, legend, children, style }) {
  return (
    <View style={[s.section, style]}>
      <View style={[s.row, { justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }]}>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>{title}</Text>
          {sub ? <Text style={[s.sub, { marginTop: 4 }]}>{sub}</Text> : null}
        </View>
        {legend}
      </View>
      {children}
    </View>
  );
}

function Legend({ items }) {
  return (
    <View style={[s.row, { gap: 14 }]}>
      {items.map(([label, c]) => (
        <View key={label} style={[s.row, { gap: 6 }]}>
          <View style={{ width: 9, height: 9, borderRadius: 2, backgroundColor: c }} />
          <Text style={s.sub}>{label}</Text>
        </View>
      ))}
    </View>
  );
}

const NoData = ({ body }) => (
  <EmptyState icon={<Chart size={22} color={color.faint} />} title="No requests yet" body={body} />
);

// ── Request volume ───────────────────────────────────────────────

function VolumeChart({ history, range, now }) {
  const days = Math.min(range, 30);
  const buckets = useMemo(() => {
    const out = Array.from({ length: days }, (_, i) => {
      const start = new Date(now - (days - 1 - i) * DAY); start.setHours(0, 0, 0, 0);
      return { t: start.getTime(), critical: 0, other: 0 };
    });
    history.forEach((h) => {
      const d = new Date(h.createdAt); d.setHours(0, 0, 0, 0);
      const b = out.find((x) => x.t === d.getTime());
      if (b) b[h.urgency === 'critical' ? 'critical' : 'other'] += 1;
    });
    return out;
  }, [history, days, now]);
  const peak = Math.max(1, ...buckets.map((b) => b.critical + b.other));
  const fmt = (t) => new Date(t).toLocaleDateString([], { day: 'numeric', month: 'short' });

  return (
    <Section title="Emergency request volume" sub={`Requests per day, last ${days} days`}
      legend={<Legend items={[['Routine & urgent', color.blue], ['Critical', color.red]]} />}
      style={{ flex: 1, minWidth: 0 }}>
      {history.length === 0 ? <NoData body="Every request you trigger is counted here by day and urgency." /> : (
        <>
          <View style={s.bars}>
            {buckets.map((b) => (
              <View key={b.t} style={s.barCol} accessibilityLabel={`${fmt(b.t)}: ${b.critical + b.other} requests, ${b.critical} critical`}>
                <View style={{ height: `${(b.critical / peak) * 100}%`, backgroundColor: color.red, borderTopLeftRadius: 3, borderTopRightRadius: 3 }} />
                <View style={{ height: `${(b.other / peak) * 100}%`, backgroundColor: color.blue, opacity: 0.82, borderTopLeftRadius: b.critical ? 0 : 3, borderTopRightRadius: b.critical ? 0 : 3 }} />
              </View>
            ))}
          </View>
          <View style={[s.row, { justifyContent: 'space-between', marginTop: 9 }]}>
            <Text style={s.axis}>{fmt(buckets[0].t)}</Text>
            <Text style={s.axis}>{fmt(buckets[Math.floor(days / 2)].t)}</Text>
            <Text style={s.axis}>Today</Text>
          </View>
        </>
      )}
    </Section>
  );
}

// ── Funnel ───────────────────────────────────────────────────────

function Funnel({ history }) {
  const t = history.reduce((a, h) => ({
    matched: a.matched + (h.matched || 0), contacted: a.contacted + (h.contacted || 0),
    answered: a.answered + (h.answered || 0), accepted: a.accepted + (h.accepted || 0), donated: a.donated + (h.donated || 0),
  }), { matched: 0, contacted: 0, answered: 0, accepted: 0, donated: 0 });

  const steps = [
    ['Eligible donors matched', t.matched, color.blue, 1],
    ['Contacted by AI voice', t.contacted, color.blue, 0.8],
    ['Answered', t.answered, color.blue, 0.6],
    ['Accepted', t.accepted, color.green, 1],
    ['Donation completed', t.donated, color.green, 1],
  ];
  const top = Math.max(1, t.matched);
  const rate = (a, b) => (b ? `${Math.round((a / b) * 100)}%` : '—');
  const conv = [rate(t.contacted, t.matched) + ' dialled', rate(t.answered, t.contacted) + ' answered',
    rate(t.accepted, t.answered) + ' accepted', rate(t.donated, t.accepted) + ' donated'];
  const pickup = t.contacted ? t.answered / t.contacted : null;

  return (
    <Section title="Response funnel" sub="Where donors drop off, across the period" style={{ width: 460 }}>
      {history.length === 0 ? <NoData body="Shows how many matched donors were reached, answered and gave blood." /> : (
        <View style={{ gap: 6 }}>
          {steps.map(([label, n, c, op], i) => (
            <View key={label}>
              <View style={[s.row, { justifyContent: 'space-between', marginBottom: 5 }]}>
                <Text style={s.funnelLabel}>{label}</Text>
                <Num size={15} tone={c === color.green && n ? 'green' : undefined}>{n.toLocaleString()}</Num>
              </View>
              <View style={s.track}><View style={{ width: `${Math.max(1, (n / top) * 100)}%`, height: 11, borderRadius: 3, backgroundColor: c, opacity: op }} /></View>
              {i < conv.length && <Text style={[s.axis, { marginTop: 5 }]}>{conv[i]}</Text>}
            </View>
          ))}
          {pickup != null && pickup < 0.5 && (
            <View style={[s.row, s.insight]}>
              <AlertIcon size={14} color={color.amber} />
              <Text style={s.insightText}>
                Pickup is the biggest loss: {Math.round(pickup * 100)}% of calls are answered. Widening the radius adds donors; it does not fix pickup.
              </Text>
            </View>
          )}
        </View>
      )}
    </Section>
  );
}

// ── Blood availability: demand vs donors ready now ───────────────

function Availability({ store, history, range }) {
  const a = store.availability;
  const demand = useMemo(() => {
    const d = {};
    history.forEach((h) => { d[h.bloodGroup] = (d[h.bloodGroup] || 0) + (h.units || 1); });
    return d;
  }, [history]);
  const available = a.data?.groups || {};
  const rows = GROUP_ORDER.map((g) => {
    const need = demand[g] || 0;
    const have = available[g] ?? 0;
    const short = a.status === 'ready' && (have === 0 || have < need);
    return { g, need, have, short };
  });
  const peak = Math.max(1, ...rows.map((r) => Math.max(r.need, r.have)));
  const shortages = rows.filter((r) => r.short);

  return (
    <Section
      title="Blood group demand vs available donors"
      sub={a.status === 'ready' ? `Units requested (${range} days) against donors eligible within ${a.data.radius_km} km right now` : 'Units requested against donors eligible right now'}
      legend={<Legend items={[['Demand', color.blue], ['Available', color.green]]} />}
      style={{ width: 700 }}
    >
      {a.status === 'error' ? (
        <EmptyState title="Availability unavailable" body={a.error} />
      ) : (
        <>
          {shortages.length > 0 && (
            <View style={s.shortBanner}>
              <LiveDot tone="red" size={6} pulse={false} />
              <Text style={s.shortText}>
                Shortage risk: {shortages.map((r) => bg(r.g)).join(', ')}. Consider a donor drive or pre-alerting neighbouring blood banks.
              </Text>
            </View>
          )}
          {rows.map((r) => (
            <View key={r.g} style={[s.row, s.availRow, r.short && { backgroundColor: '#FFF8F7' }]}>
              <Text style={[s.availGroup, r.short && { color: color.redText }]}>{bg(r.g)}</Text>
              <View style={{ flex: 1, gap: 4 }}>
                <View style={{ width: `${(r.need / peak) * 100}%`, minWidth: r.need ? 3 : 0, height: 10, borderRadius: 3, backgroundColor: color.blue }} />
                <View style={{ width: `${(r.have / peak) * 100}%`, minWidth: r.have ? 3 : 0, height: 10, borderRadius: 3, backgroundColor: r.short ? '#E8A9A3' : color.green }} />
              </View>
              <Text style={s.availNums}>{r.need} req · {a.status === 'ready' ? `${r.have} ready` : '…'}</Text>
              <Text style={[s.availFlag, r.short && { color: color.redText }]}>
                {a.status !== 'ready' ? '' : r.short ? (r.have === 0 ? 'NONE READY' : `SHORT BY ${r.need - r.have}`) : r.need ? 'Healthy' : 'No demand'}
              </Text>
            </View>
          ))}
        </>
      )}
    </Section>
  );
}

// ── Time to first acceptance ─────────────────────────────────────

function ResponseTimes({ history }) {
  const times = history.filter((h) => h.firstAcceptAt).map((h) => h.firstAcceptAt - h.createdAt);
  const buckets = Array.from({ length: 12 }, (_, i) => ({ i, n: 0 }));
  times.forEach((ms) => { buckets[Math.min(11, Math.floor(ms / 60000))].n += 1; });
  const peak = Math.max(1, ...buckets.map((b) => b.n));
  const med = percentile(times, 50);
  const p90 = percentile(times, 90);
  const slow = times.length ? Math.max(...times) : null;

  return (
    <Section title="Time to first acceptance" sub={`Across ${times.length} request${times.length === 1 ? '' : 's'} with an acceptance`} style={{ flex: 1, minWidth: 0 }}>
      {times.length === 0 ? <NoData body="Measures trigger-to-first-yes for every request. Target: under 3 minutes." /> : (
        <>
          <View style={[s.row, { gap: 30 }]}>
            <Stat label="MEDIAN" value={formatDuration(med)} tone="green" />
            <Stat label="P90" value={formatDuration(p90)} />
            <Stat label="SLOWEST" value={formatDuration(slow)} tone={slow > 10 * 60000 ? 'amber' : undefined} />
          </View>
          <View style={[s.bars, { height: 120, marginTop: 18 }]}>
            {buckets.map((b) => (
              <View key={b.i} style={s.barCol} accessibilityLabel={`${b.i} to ${b.i + 1} minutes: ${b.n}`}>
                <View style={{ height: `${(b.n / peak) * 100}%`, borderTopLeftRadius: 3, borderTopRightRadius: 3,
                  backgroundColor: b.i < 3 ? color.green : b.i < 8 ? color.blue : color.amber, opacity: b.i < 3 ? 1 : 0.7 }} />
              </View>
            ))}
          </View>
          <View style={[s.row, { justifyContent: 'space-between', marginTop: 9 }]}>
            {['0 min', '3 min', '6 min', '9 min', '12 min+'].map((t) => <Text key={t} style={s.axis}>{t}</Text>)}
          </View>
        </>
      )}
    </Section>
  );
}

function Stat({ label, value, tone }) {
  return (
    <View>
      <Label>{label}</Label>
      <Num size={22} tone={tone} style={{ marginTop: 4 }}>{value}</Num>
    </View>
  );
}

// ── History table ────────────────────────────────────────────────

const STATUS_PILL = {
  active: ['Active', 'red'], fulfilled: ['Fulfilled', 'green'], partial: ['Partial', 'amber'], closed: ['Closed', 'muted'],
};

function HistoryTable({ history, now }) {
  const [status, setStatus] = useState('all');
  const [group, setGroup] = useState('all');
  const [asc, setAsc] = useState(false);

  const rows = useMemo(() => history
    .filter((h) => status === 'all' || h.status === status || (status === 'closed' && h.status === 'partial'))
    .filter((h) => group === 'all' || h.bloodGroup === group)
    .sort((a, b) => (asc ? a.createdAt - b.createdAt : b.createdAt - a.createdAt)), [history, status, group, asc]);

  return (
    <Panel>
      <View style={[s.row, { justifyContent: 'space-between', padding: 14, paddingHorizontal: 20, flexWrap: 'wrap', gap: 10 }]}>
        <View style={[s.row, { gap: 12 }]}>
          <Text style={s.title}>Request history</Text>
          <Text style={s.sub}>{rows.length} of {history.length} records</Text>
        </View>
        <View style={[s.row, { gap: 10, flexWrap: 'wrap' }]}>
          <Segmented value={status} onChange={setStatus} options={[
            { value: 'all', label: 'All' }, { value: 'fulfilled', label: 'Fulfilled' },
            { value: 'active', label: 'Open', tone: 'red' }, { value: 'closed', label: 'Closed' },
          ]} />
          <Segmented value={group} onChange={setGroup}
            options={[{ value: 'all', label: 'Any group' }, ...BLOOD_GROUPS.map((g) => ({ value: g, label: bg(g) }))]} />
        </View>
      </View>
      <View style={[s.row, s.th]}>
        <Text style={[s.thText, { flex: 0.7 }]}>BLOOD</Text>
        <Text style={[s.thText, { flex: 0.6 }]}>UNITS</Text>
        <Text style={[s.thText, { flex: 1.5 }]}>PATIENT / REF</Text>
        <Pressable onPress={() => setAsc(!asc)} accessibilityRole="button" style={{ flex: 1.2 }}>
          <Text style={[s.thText, { color: color.text2 }]}>TRIGGERED {asc ? '↑' : '↓'}</Text>
        </Pressable>
        <Text style={[s.thText, { flex: 1 }]}>CONTACTED</Text>
        <Text style={[s.thText, { flex: 0.9 }]}>ACCEPTED</Text>
        <Text style={[s.thText, { flex: 1.1 }]}>TIME TO FIRST YES</Text>
        <Text style={[s.thText, { flex: 1, textAlign: 'right' }]}>STATUS</Text>
      </View>
      {rows.length === 0 ? (
        <EmptyState title={history.length ? 'Nothing matches these filters' : 'No requests recorded yet'}
          body={history.length ? 'Clear a filter to see more.' : 'Requests you trigger from this browser are recorded here with their outcomes.'} />
      ) : rows.slice(0, 50).map((h) => {
        const [label, tone] = STATUS_PILL[h.status] || ['—', 'muted'];
        const ttf = h.firstAcceptAt ? h.firstAcceptAt - h.createdAt : null;
        return (
          <View key={h.id} style={[s.row, s.tr, h.status === 'active' && { backgroundColor: '#FFFBFA' }]}>
            <Text style={[s.cellGroup, { flex: 0.7 }]}>{bg(h.bloodGroup)}</Text>
            <Text style={[s.cell, { flex: 0.6 }]}>{h.units}</Text>
            <Text style={[s.cellStrong, { flex: 1.5 }]} numberOfLines={1}>{h.patient || '—'}</Text>
            <Text style={[s.cell, { flex: 1.2 }]}>
              {new Date(h.createdAt).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
            </Text>
            <Text style={[s.cell, { flex: 1 }]}>{h.contacted ?? '—'}</Text>
            <Text style={[s.cell, { flex: 0.9, color: h.accepted ? color.greenText : color.text2, fontWeight: h.accepted ? '600' : '400' }]}>{h.accepted ?? 0}</Text>
            <Text style={[s.cell, { flex: 1.1, color: ttf == null ? color.muted : ttf > 10 * 60000 ? color.amberText : color.greenText, fontWeight: ttf == null ? '400' : '600' }]}>
              {ttf == null ? (h.status === 'active' ? 'In progress' : '—') : formatDuration(ttf)}
            </Text>
            <View style={{ flex: 1, alignItems: 'flex-end' }}><Pill tone={tone}>{label}</Pill></View>
          </View>
        );
      })}
    </Panel>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  sub: { fontFamily: font.body, fontSize: 12, color: color.text2 },
  axis: { fontFamily: font.body, fontSize: 11, color: color.muted },
  title: { fontFamily: font.display, fontSize: 15, fontWeight: '600', color: color.text },

  kpis: { flexDirection: 'row', paddingHorizontal: 22, paddingTop: 18, paddingBottom: 16, borderBottomWidth: 1, borderBottomColor: '#E9ECF2' },
  kpi: { flexGrow: 1, flexBasis: 0, paddingHorizontal: 20, borderRightWidth: 1, borderRightColor: '#E9ECF2', minWidth: 0 },

  split: { flexDirection: 'row', backgroundColor: color.surface, borderWidth: 1, borderColor: color.border, borderRadius: 11, overflow: 'hidden' },
  vDivider: { width: 1, backgroundColor: color.borderSoft },
  hDivider: { height: 1, backgroundColor: color.borderSoft },
  section: { padding: 20 },

  bars: { flexDirection: 'row', alignItems: 'flex-end', gap: 5, height: 160, borderBottomWidth: 1, borderBottomColor: '#E9ECF2' },
  barCol: { flex: 1, height: '100%', justifyContent: 'flex-end' },

  funnelLabel: { fontFamily: font.body, fontSize: 12.5, color: color.text2 },
  track: { backgroundColor: color.track, borderRadius: 3 },
  insight: { gap: 9, marginTop: 10, paddingTop: 12, borderTopWidth: 1, borderTopColor: color.borderSoft, alignItems: 'flex-start' },
  insightText: { flex: 1, fontFamily: font.body, fontSize: 12, color: color.text2, lineHeight: 17 },

  shortBanner: { flexDirection: 'row', alignItems: 'center', gap: 9, backgroundColor: color.redSurface, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 9, marginBottom: 10 },
  shortText: { flex: 1, fontFamily: font.body, fontSize: 12, color: color.redText, fontWeight: '500' },
  availRow: { gap: 14, paddingVertical: 7, paddingHorizontal: 10, borderRadius: 8 },
  availGroup: { width: 40, fontFamily: font.display, fontSize: 15, fontWeight: '700', color: color.text },
  availNums: { width: 118, textAlign: 'right', fontFamily: font.body, fontSize: 11.5, color: color.text2 },
  availFlag: { width: 96, textAlign: 'right', fontFamily: font.body, fontSize: 11, fontWeight: '600', letterSpacing: 0.3, color: color.muted },

  th: { paddingHorizontal: 20, paddingVertical: 9, gap: 14, backgroundColor: color.surface2, borderTopWidth: 1, borderBottomWidth: 1, borderColor: color.borderSoft },
  thText: { fontFamily: font.body, fontSize: 11, fontWeight: '600', color: color.muted, letterSpacing: 0.5 },
  tr: { paddingHorizontal: 20, paddingVertical: 12, gap: 14, borderBottomWidth: 1, borderBottomColor: color.divider },
  cell: { fontFamily: font.body, fontSize: 13, color: color.text2 },
  cellStrong: { fontFamily: font.body, fontSize: 13.5, fontWeight: '600', color: color.text },
  cellGroup: { fontFamily: font.display, fontSize: 14, fontWeight: '600', color: color.text },
});
