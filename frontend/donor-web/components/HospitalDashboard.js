// HaemNet hospital dashboard: app shell, navigation and screen routing.
// Data and backend logic live in useDispatchStore; screens are in ./screens.

import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Activity, Chart, HaemNetMark, LogOut, Map as MapIcon, Plus } from './Icons';
import { color, font, loadWebFonts } from './theme';
import { Button, LiveDot } from './ui';
import { useDispatchStore } from './useDispatchStore';
import LoginScreen from './screens/LoginScreen';
import CommandCenter from './screens/CommandCenter';
import DispatchMap from './screens/DispatchMap';
import NetworkIntelligence from './screens/NetworkIntelligence';
import NewRequestDrawer from './screens/NewRequestDrawer';

const NAV = [
  { key: 'command', label: 'Command Center', Icon: Activity },
  { key: 'map', label: 'Dispatch Map', Icon: MapIcon },
  { key: 'intel', label: 'Network Intelligence', Icon: Chart },
];

const TITLES = { command: 'Command Center', map: 'Dispatch Map', intel: 'Network Intelligence' };

export default function HospitalDashboard() {
  useEffect(loadWebFonts, []);
  const store = useDispatchStore();
  const { width } = useWindowDimensions();
  const [tab, setTab] = useState('command');
  const [drawerOpen, setDrawerOpen] = useState(false);

  if (store.booting) {
    return (
      <View style={[s.root, { alignItems: 'center', justifyContent: 'center' }]}>
        <ActivityIndicator color={color.text} />
      </View>
    );
  }
  if (!store.profile) return <LoginScreen store={store} />;

  const compactNav = width < 1180;
  const compactBody = width < 1320;
  const open = store.ordered.filter((e) => !e.closed);
  const critical = open.filter((e) => e.urgency === 'critical').length;

  return (
    <View style={s.root}>
      <Sidebar compact={compactNav} tab={tab} setTab={setTab} store={store} openCount={open.length} />

      <View style={s.main}>
        <View style={s.topbar}>
          <View style={[s.row, { flexShrink: 1 }]}>
            <Text style={s.title}>{TITLES[tab]}</Text>
            <View style={s.divider} />
            <Text style={s.subtitle} numberOfLines={1}>{store.profile.name || store.profile.id}</Text>
          </View>
          <View style={[s.row, { gap: 12 }]}>
            {critical > 0 && (
              <View style={s.critChip}>
                <LiveDot tone="red" size={6} />
                <Text style={s.critText}>{critical} critical active</Text>
              </View>
            )}
            <ConnectionChip state={store.wsState} onRetry={store.reconnect} />
            <Button
              onPress={() => setDrawerOpen(true)}
              icon={<Plus size={14} color="#FFFFFF" />}
              accessibilityLabel="New emergency request"
            >
              {compactNav ? 'New request' : 'New emergency request'}
            </Button>
          </View>
        </View>

        <View style={{ flex: 1 }}>
          {tab === 'command' && <CommandCenter store={store} compact={compactBody} onNew={() => setDrawerOpen(true)} />}
          {tab === 'map' && <DispatchMap store={store} compact={compactBody} />}
          {tab === 'intel' && <NetworkIntelligence store={store} compact={compactBody} />}
        </View>
      </View>

      <NewRequestDrawer
        visible={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        store={store}
        onCreated={() => { setDrawerOpen(false); setTab('command'); }}
      />
    </View>
  );
}

function Sidebar({ compact, tab, setTab, store, openCount }) {
  const healthy = store.wsState === 'live' && store.health?.dbOk;
  const initials = (store.profile.name || store.profile.id || '?')
    .split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase();
  const statusText = healthy
    ? 'Network operational'
    : store.wsState !== 'live' ? 'Live feed reconnecting' : 'Database degraded';

  return (
    <View style={[s.sidebar, compact && { width: 68 }]}>
      <View style={[s.brand, compact && { justifyContent: 'center', paddingHorizontal: 0 }]}>
        <HaemNetMark size={26} />
        {!compact && <Text style={s.brandText}>HaemNet</Text>}
      </View>

      <View style={{ paddingHorizontal: compact ? 10 : 12, paddingTop: 8 }}>
        {!compact && <Text style={s.navSection}>OPERATIONS</Text>}
        {NAV.map(({ key, label, Icon }) => {
          const active = tab === key;
          return (
            <Pressable
              key={key}
              onPress={() => setTab(key)}
              accessibilityRole="link"
              accessibilityLabel={label}
              style={({ hovered }) => [s.navItem, compact && s.navCompact, active && s.navActive, hovered && !active && s.navHover]}
            >
              <Icon size={16} color={active ? color.blue : color.muted} />
              {!compact && <Text style={[s.navText, active && s.navTextActive]}>{label}</Text>}
              {!compact && key === 'command' && openCount > 0 && (
                <View style={s.navBadge}><Text style={s.navBadgeText}>{openCount}</Text></View>
              )}
            </Pressable>
          );
        })}
      </View>

      <View style={{ flex: 1 }} />

      <View style={{ padding: compact ? 10 : 16 }}>
        <View
          style={[s.status, !healthy && s.statusWarn, compact && { justifyContent: 'center' }]}
          accessibilityLabel={statusText}
        >
          <LiveDot tone={healthy ? 'green' : 'amber'} size={6} pulse={healthy} />
          {!compact && <Text style={[s.statusText, !healthy && { color: color.amberText }]}>{statusText}</Text>}
        </View>
        <Pressable
          onPress={store.logout}
          accessibilityRole="button"
          accessibilityLabel="Sign out"
          style={[s.profile, compact && { justifyContent: 'center' }]}
        >
          <View style={s.avatar}><Text style={s.avatarText}>{initials}</Text></View>
          {!compact && (
            <>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={s.profileName} numberOfLines={1}>{store.profile.name || 'Hospital'}</Text>
                <Text style={s.profileMeta} numberOfLines={1}>{store.profile.id} · Sign out</Text>
              </View>
              <LogOut size={14} color={color.faint} />
            </>
          )}
        </Pressable>
      </View>
    </View>
  );
}

function ConnectionChip({ state, onRetry }) {
  if (state === 'live') {
    return (
      <View style={[s.connChip, { backgroundColor: color.greenBand }]}>
        <LiveDot tone="green" size={6} />
        <Text style={[s.connText, { color: color.greenText }]}>Live</Text>
      </View>
    );
  }
  return (
    <Pressable onPress={onRetry} accessibilityRole="button" style={[s.connChip, { backgroundColor: color.amberSurface }]}>
      <LiveDot tone="amber" size={6} pulse={state === 'connecting'} />
      <Text style={[s.connText, { color: color.amberText }]}>{state === 'connecting' ? 'Connecting' : 'Offline · retry'}</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, flexDirection: 'row', backgroundColor: color.canvas, minHeight: '100%' },
  row: { flexDirection: 'row', alignItems: 'center' },
  main: { flex: 1, minWidth: 0 },

  sidebar: { width: 232, backgroundColor: color.surface, borderRightWidth: 1, borderRightColor: color.border },
  brand: { height: 60, flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 18 },
  brandText: { fontFamily: font.display, fontSize: 17, fontWeight: '700', color: color.text, letterSpacing: -0.3 },
  navSection: { fontFamily: font.body, fontSize: 10.5, fontWeight: '600', color: color.muted, letterSpacing: 0.8, paddingHorizontal: 10, paddingTop: 12, paddingBottom: 8 },
  navItem: { flexDirection: 'row', alignItems: 'center', gap: 11, paddingHorizontal: 10, paddingVertical: 9, borderRadius: 7, marginBottom: 1 },
  navCompact: { justifyContent: 'center', paddingHorizontal: 0 },
  navActive: { backgroundColor: color.selected },
  navHover: { backgroundColor: color.surface2 },
  navText: { fontFamily: font.body, fontSize: 13.5, color: color.text2, flex: 1 },
  navTextActive: { fontWeight: '600', color: color.text },
  navBadge: { backgroundColor: color.redSurface, paddingHorizontal: 7, paddingVertical: 1, borderRadius: 5 },
  navBadgeText: { fontFamily: font.mono, fontSize: 10.5, color: color.redText },
  status: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: 10, borderRadius: 8, backgroundColor: color.greenBand, marginBottom: 12 },
  statusWarn: { backgroundColor: color.amberSurface },
  statusText: { fontFamily: font.body, fontSize: 11.5, fontWeight: '600', color: color.greenText },
  profile: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingTop: 12, borderTopWidth: 1, borderTopColor: color.borderSoft },
  avatar: { width: 28, height: 28, borderRadius: 14, backgroundColor: color.selected, alignItems: 'center', justifyContent: 'center' },
  avatarText: { fontFamily: font.body, fontSize: 10, fontWeight: '600', color: color.text2 },
  profileName: { fontFamily: font.body, fontSize: 12, fontWeight: '600', color: color.text },
  profileMeta: { fontFamily: font.body, fontSize: 10.5, color: color.muted, marginTop: 1 },

  topbar: {
    height: 60, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 22, backgroundColor: color.surface, borderBottomWidth: 1, borderBottomColor: color.border,
  },
  title: { fontFamily: font.display, fontSize: 17, fontWeight: '700', color: color.text, letterSpacing: -0.25 },
  divider: { width: 1, height: 18, backgroundColor: color.border, marginHorizontal: 14 },
  subtitle: { fontFamily: font.body, fontSize: 12.5, color: color.text2, maxWidth: 320 },
  critChip: { flexDirection: 'row', alignItems: 'center', gap: 7, backgroundColor: color.redSurface, paddingHorizontal: 11, paddingVertical: 6, borderRadius: 6 },
  critText: { fontFamily: font.body, fontSize: 12, fontWeight: '600', color: color.redText },
  connChip: { flexDirection: 'row', alignItems: 'center', gap: 7, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6 },
  connText: { fontFamily: font.body, fontSize: 12, fontWeight: '600' },
});
