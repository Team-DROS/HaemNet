import React from 'react';
import Svg, { Path, Circle, Polyline, Rect, Line, Ellipse, Polygon } from 'react-native-svg';

export const Activity = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Path d="M22 12h-4l-3 9L9 3l-3 9H2" />
  </Svg>
);

export const Phone = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
  </Svg>
);

export const ShieldAlert = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    <Line x1="12" y1="8" x2="12" y2="12" />
    <Line x1="12" y1="16" x2="12.01" y2="16" />
  </Svg>
);

export const CheckCircle2 = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Circle cx="12" cy="12" r="10" />
    <Path d="m9 12 2 2 4-4" />
  </Svg>
);

export const XCircle = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Circle cx="12" cy="12" r="10" />
    <Line x1="15" y1="9" x2="9" y2="15" />
    <Line x1="9" y1="9" x2="15" y2="15" />
  </Svg>
);

export const MapPin = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
    <Circle cx="12" cy="10" r="3" />
  </Svg>
);

export const Sparkles = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
  </Svg>
);

export const Clock = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Circle cx="12" cy="12" r="10" />
    <Polyline points="12 6 12 12 16 14" />
  </Svg>
);

export const HeartHandshake = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" />
    <Path d="M12 5 9.04 7.96a2.1 2.1 0 0 0 0 2.97v0a2.1 2.1 0 0 0 2.97 0L15 8" />
  </Svg>
);

export const Wifi = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Path d="M5 12.55a11 11 0 0 1 14.08 0" />
    <Path d="M1.42 9a16 16 0 0 1 21.16 0" />
    <Path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
    <Line x1="12" y1="20" x2="12.01" y2="20" />
  </Svg>
);

export const WifiOff = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Path d="M1 1l22 22" />
    <Path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
    <Path d="M5 12.55a10.94 10.94 0 0 1 5.83-2.84" />
    <Path d="M12 20h.01" />
    <Path d="M8.53 16.11a6 6 0 0 1 4.56-1.5" />
  </Svg>
);

export const Database = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Ellipse cx="12" cy="5" rx="9" ry="3" />
    <Path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    <Path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3" />
  </Svg>
);

export const User = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
    <Circle cx="12" cy="7" r="4" />
  </Svg>
);

export const Heart = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" />
  </Svg>
);

export const Calendar = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
    <Line x1="16" y1="2" x2="16" y2="6" />
    <Line x1="8" y1="2" x2="8" y2="6" />
    <Line x1="3" y1="10" x2="21" y2="10" />
  </Svg>
);

export const Award = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Circle cx="12" cy="8" r="7" />
    <Polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88" />
  </Svg>
);

export const AlertCircle = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Circle cx="12" cy="12" r="10" />
    <Line x1="12" y1="8" x2="12" y2="12" />
    <Line x1="12" y1="16" x2="12.01" y2="16" />
  </Svg>
);

export const RotateCcw = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Path d="M1 4v6h6" />
    <Path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
  </Svg>
);

export const Check = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Polyline points="20 6 9 17 4 12" />
  </Svg>
);

export const Map = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21" />
  </Svg>
);

export const Lock = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
    <Path d="M7 11V7a5 5 0 0 1 10 0v4" />
  </Svg>
);

export const LogOut = ({ size = 24, color = "currentColor", ...props }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <Path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
    <Polyline points="16 17 21 12 16 7" />
    <Line x1="21" y1="12" x2="9" y2="12" />
  </Svg>
);

// ── Added for the light-first redesign ───────────────────────────
const stroke = (color, strokeWidth = 2) => ({
  fill: 'none', stroke: color, strokeWidth, strokeLinecap: 'round', strokeLinejoin: 'round',
});

export const Plus = ({ size = 24, color = 'currentColor', strokeWidth = 2.4 }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" {...stroke(color, strokeWidth)}>
    <Path d="M12 5v14M5 12h14" />
  </Svg>
);

export const X = ({ size = 24, color = 'currentColor' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" {...stroke(color, 2.4)}>
    <Path d="M18 6 6 18M6 6l12 12" />
  </Svg>
);

export const Mic = ({ size = 24, color = 'currentColor' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" {...stroke(color)}>
    <Path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
    <Path d="M19 10v2a7 7 0 0 1-14 0v-2" />
  </Svg>
);

export const Users = ({ size = 24, color = 'currentColor' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" {...stroke(color)}>
    <Path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
    <Circle cx="9" cy="7" r="4" />
    <Path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
  </Svg>
);

export const Chart = ({ size = 24, color = 'currentColor' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" {...stroke(color)}>
    <Path d="M3 3v18h18" />
    <Path d="m7 15 4-6 4 4 5-8" />
  </Svg>
);

export const Alert = ({ size = 24, color = 'currentColor' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" {...stroke(color)}>
    <Path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" />
  </Svg>
);

export const Navigation = ({ size = 24, color = 'currentColor' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" {...stroke(color)}>
    <Path d="M3 11 22 2l-9 19-2-8-8-2z" />
  </Svg>
);

export const Network = ({ size = 24, color = 'currentColor' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" {...stroke(color)}>
    <Circle cx="12" cy="5" r="2.5" />
    <Circle cx="5" cy="19" r="2.5" />
    <Circle cx="19" cy="19" r="2.5" />
    <Path d="M12 7.5v5M10 14l-3.5 3M14 14l3.5 3" />
  </Svg>
);

export const Hospital = ({ size = 24, color = 'currentColor' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" {...stroke(color)}>
    <Path d="M3 21h18M5 21V7l7-4 7 4v14" />
    <Path d="M12 10v5M9.5 12.5h5" />
  </Svg>
);

export const Download = ({ size = 24, color = 'currentColor' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" {...stroke(color)}>
    <Path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
  </Svg>
);

// HaemNet mark: a droplet holding three connected nodes, one of them red.
export const HaemNetMark = ({ size = 26, color = '#0F1A2B', accent = '#D92D20' }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24">
    <Path d="M12 2.6c-3.4 4.2-5.7 7-5.7 9.9a5.7 5.7 0 0 0 11.4 0c0-2.9-2.3-5.7-5.7-9.9z" fill="none" stroke={color} strokeWidth={1.5} />
    <Path d="M12 9.6 9.2 14.4M12 9.6l2.8 4.8M9.2 14.4h5.6" stroke={color} strokeWidth={1} opacity={0.55} />
    <Circle cx="12" cy="9.6" r="1.7" fill={accent} />
    <Circle cx="9.2" cy="14.4" r="1.3" fill={color} />
    <Circle cx="14.8" cy="14.4" r="1.3" fill={color} />
  </Svg>
);
