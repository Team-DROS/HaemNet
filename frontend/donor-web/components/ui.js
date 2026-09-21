// Small shared building blocks for the hospital dashboard.

import React, { useEffect, useRef } from 'react';
import { Animated, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { color, font, radius, STATUS, toneColor, toneText } from './theme';

const useNative = Platform.OS !== 'web';

// A dot that softly pulses; used for anything live (calling, active emergency).
export function LiveDot({ tone = 'blue', size = 8, pulse = true }) {
  const anim = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!pulse) return undefined;
    const loop = Animated.loop(
      Animated.timing(anim, { toValue: 1, duration: 1800, useNativeDriver: useNative }),
    );
    loop.start();
    return () => loop.stop();
  }, [anim, pulse]);
  const c = toneColor[tone] || tone;
  return (
    <View style={{ width: size, height: size }}>
      {pulse && (
        <Animated.View
          style={{
            position: 'absolute', width: size, height: size, borderRadius: size / 2, backgroundColor: c,
            opacity: anim.interpolate({ inputRange: [0, 1], outputRange: [0.45, 0] }),
            transform: [{ scale: anim.interpolate({ inputRange: [0, 1], outputRange: [1, 2.6] }) }],
          }}
        />
      )}
      <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: c }} />
    </View>
  );
}

export function Label({ children, style, tone }) {
  return <Text style={[s.label, tone && { color: toneText[tone] }, style]}>{children}</Text>;
}

export function Mono({ children, style }) {
  return <Text style={[s.mono, style]}>{children}</Text>;
}

export function Num({ children, size = 27, tone, style }) {
  return (
    <Text style={[s.num, { fontSize: size }, tone && { color: toneText[tone] }, style]}>{children}</Text>
  );
}

// Donor status: a coloured dot plus plain text; pills only where emphasis helps.
export function StatusCell({ status }) {
  const meta = STATUS[status] || { label: status || 'Unknown', tone: 'muted' };
  if (meta.pill) return <Pill tone={meta.tone}>{meta.label}</Pill>;
  return (
    <View style={s.row}>
      <LiveDot tone={meta.tone} size={7} pulse={!!meta.live} />
      <Text style={[s.statusText, { color: toneText[meta.tone] }, meta.live && { fontWeight: '600' }]}>
        {meta.label}
      </Text>
    </View>
  );
}

const pillBg = {
  green: color.greenSurface, blue: color.blueSurface, amber: color.amberSurface,
  red: color.redSurface, violet: color.violetSurface, muted: color.track,
};

export function Pill({ tone = 'muted', children, style }) {
  return (
    <View style={[s.pill, { backgroundColor: pillBg[tone] }, style]}>
      <Text style={[s.pillText, { color: toneText[tone] }]}>{children}</Text>
    </View>
  );
}

export function Button({ children, onPress, variant = 'primary', disabled, icon, style, textStyle, accessibilityLabel }) {
  const v = VARIANTS[variant];
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      style={({ hovered, pressed }) => [
        s.btn, v.base, hovered && v.hover, pressed && { opacity: 0.85 },
        disabled && { opacity: 0.45 }, style,
      ]}
    >
      {icon}
      {typeof children === 'string' ? <Text style={[s.btnText, v.text, textStyle]}>{children}</Text> : children}
    </Pressable>
  );
}

const VARIANTS = {
  primary: { base: { backgroundColor: color.text }, hover: { backgroundColor: '#1D2A40' }, text: { color: '#FFFFFF' } },
  danger: { base: { backgroundColor: color.red }, hover: { backgroundColor: '#C22418' }, text: { color: '#FFFFFF' } },
  secondary: {
    base: { backgroundColor: color.surface, borderWidth: 1, borderColor: color.border },
    hover: { backgroundColor: color.surface2 }, text: { color: color.text2 },
  },
  outlineDanger: {
    base: { backgroundColor: color.surface, borderWidth: 1, borderColor: '#F3C9C4' },
    hover: { backgroundColor: color.redBand }, text: { color: color.redText },
  },
  success: { base: { backgroundColor: color.green }, hover: { backgroundColor: '#0B8A5F' }, text: { color: '#FFFFFF' } },
  ghost: { base: {}, hover: { backgroundColor: color.track }, text: { color: color.text2 } },
};

// Segmented control used for filters and tabs.
export function Segmented({ options, value, onChange, style }) {
  return (
    <View style={[s.segWrap, style]}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <Pressable
            key={o.value}
            onPress={() => onChange(o.value)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            style={[s.segItem, active && s.segActive]}
          >
            <Text style={[s.segText, active && s.segTextActive, o.tone && !active && { color: toneText[o.tone] }]}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Panel({ children, style }) {
  return <View style={[s.panel, style]}>{children}</View>;
}

export function EmptyState({ icon, title, body, action }) {
  return (
    <View style={s.empty}>
      {icon}
      <Text style={s.emptyTitle}>{title}</Text>
      {body ? <Text style={s.emptyBody}>{body}</Text> : null}
      {action ? <View style={{ marginTop: 16 }}>{action}</View> : null}
    </View>
  );
}

// Minutes:seconds since a timestamp.
export function formatElapsed(ms) {
  if (ms == null || ms < 0) return '00:00';
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
}

export function formatDuration(ms) {
  if (ms == null) return '—';
  const total = Math.round(ms / 1000);
  const m = Math.floor(total / 60);
  const sec = total % 60;
  return `${m}:${String(sec).padStart(2, '0')}`;
}

export function formatClock(ms) {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  label: { fontFamily: font.body, fontSize: 11, fontWeight: '600', color: color.muted, letterSpacing: 0.55 },
  mono: { fontFamily: font.mono, fontSize: 11, color: color.muted },
  num: { fontFamily: font.display, fontWeight: '700', color: color.text, letterSpacing: -0.3, lineHeight: undefined },
  statusText: { fontFamily: font.body, fontSize: 13, marginLeft: 8 },
  pill: { alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.chip },
  pillText: { fontFamily: font.body, fontSize: 12, fontWeight: '600' },
  btn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 7,
    paddingHorizontal: 14, paddingVertical: 10, borderRadius: radius.input,
  },
  btnText: { fontFamily: font.body, fontSize: 13, fontWeight: '600' },
  segWrap: { flexDirection: 'row', backgroundColor: color.track, borderRadius: radius.control, padding: 2, gap: 2 },
  segItem: { paddingHorizontal: 11, paddingVertical: 5, borderRadius: 5 },
  segActive: { backgroundColor: color.surface, ...(Platform.OS === 'web' ? { boxShadow: '0 1px 2px rgba(16,24,40,0.06)' } : {}) },
  segText: { fontFamily: font.body, fontSize: 12, color: color.text2 },
  segTextActive: { fontWeight: '600', color: color.text },
  panel: {
    backgroundColor: color.surface, borderWidth: 1, borderColor: color.border, borderRadius: radius.panel,
    overflow: 'hidden', ...(Platform.OS === 'web' ? { boxShadow: '0 1px 2px rgba(16,24,40,0.04)' } : {}),
  },
  empty: { alignItems: 'center', justifyContent: 'center', paddingVertical: 36, paddingHorizontal: 24 },
  emptyTitle: { fontFamily: font.display, fontSize: 16, fontWeight: '600', color: color.text, marginTop: 12 },
  emptyBody: { fontFamily: font.body, fontSize: 13, color: color.text2, marginTop: 6, textAlign: 'center', maxWidth: 420, lineHeight: 19 },
});
