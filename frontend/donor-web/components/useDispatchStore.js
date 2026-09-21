// Data layer for the hospital dashboard: auth, REST calls, the live
// WebSocket feed, per-emergency lifecycle state and local request history.
//
// Screens stay presentational; everything that talks to the backend or
// derives numbers from its messages lives here.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { bg } from './theme';

export const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';
export const WS_URL = process.env.EXPO_PUBLIC_WS_URL || 'ws://localhost:8000/ws/dashboard';

const USER_KEY = '@hosp_user';
const historyKey = (id) => `@hosp_history_${id}`;
const MAX_EVENTS = 120;

const ANSWERED = new Set(['answered', 'accepted', 'en_route', 'completed', 'donated']);
const ACCEPTED = new Set(['accepted', 'en_route', 'completed', 'donated']);
const EN_ROUTE = new Set(['en_route', 'completed']);

const langName = (l) => (l ? l.charAt(0).toUpperCase() + l.slice(1) : 'English');
const toMs = (iso) => {
  if (!iso) return Date.now();
  // Backend timestamps without a zone are UTC.
  const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(t) ? Date.now() : t;
};

// ── Derived lifecycle numbers for one emergency ──────────────────

export function summarize(em) {
  const donors = Object.values(em.donors || {});
  const count = (fn) => donors.filter(fn).length;
  const contacted = donors.length;
  const answered = count((d) => d.answered || ANSWERED.has(d.status));
  const accepted = count((d) => ACCEPTED.has(d.status));
  const enRoute = count((d) => EN_ROUTE.has(d.status));
  const donated = count((d) => d.status === 'donated');
  const live = count((d) => d.status === 'ringing' || d.status === 'answered');
  const etas = donors.filter((d) => ACCEPTED.has(d.status) && d.status !== 'donated' && d.eta != null).map((d) => d.eta);
  const nextEta = etas.length ? Math.min(...etas) : null;

  let stage = 1; // matched
  if (contacted) stage = 2;
  if (answered) stage = 3;
  if (accepted) stage = 4;
  if (enRoute || donated) stage = 5;
  if (em.fulfilled || donated >= (em.units || 1)) stage = 6;

  return { contacted, answered, accepted, enRoute, donated, live, nextEta, stage,
    noAnswer: count((d) => d.status === 'no_answer'), declined: count((d) => d.status === 'declined') };
}

function newEmergency(id, fields = {}) {
  return {
    id, bloodGroup: '', units: 1, urgency: 'urgent', address: '', patient: '',
    createdAt: Date.now(), matched: 0, closed: false, fulfilled: false, firstAcceptAt: null, closedAt: null,
    donors: {}, events: [], ...fields,
  };
}

function pushEvent(em, event) {
  const events = [{ id: `${event.at}-${Math.random().toString(36).slice(2, 7)}`, ...event }, ...em.events];
  return { ...em, events: events.slice(0, MAX_EVENTS) };
}

// Turn one donor status message into a timeline event, or null.
function donorEvent(donor, status, at, eta) {
  const name = donor.name || 'Donor';
  switch (status) {
    case 'answered': return { at, tone: 'blue', kind: 'call', title: `Call answered · ${name}`, sub: 'AI checking availability and eligibility' };
    case 'no_answer': return { at, tone: 'muted', kind: 'call', title: `No answer · ${name}`, sub: 'Line unanswered or busy' };
    case 'accepted': return { at, tone: 'green', kind: 'accept', title: `${name} accepted`, sub: eta != null ? `ETA ${eta} min` : 'Confirming route' };
    case 'en_route':
    case 'completed': return { at, tone: 'green', kind: 'route', title: `${name} en route`, sub: eta != null ? `Directions sent · ETA ${eta} min` : 'Directions sent' };
    case 'declined': return { at, tone: 'muted', kind: 'call', title: `${name} declined`, sub: 'Removed from this request' };
    case 'donated': return { at, tone: 'green', kind: 'donated', title: `Donation recorded · ${name}`, sub: '56-day cooldown started' };
    default: return null;
  }
}

// Apply one WebSocket donor update to an emergency.
function applyDonorUpdate(em, msg) {
  const at = toMs(msg.timestamp);
  const prev = em.donors[msg.donor_id];
  if (prev && prev.status === msg.status) return em;

  const donor = {
    id: msg.donor_id,
    name: msg.name || prev?.name || 'Donor',
    status: msg.status,
    eta: msg.eta_minutes ?? prev?.eta ?? null,
    distance: msg.distance_km ?? prev?.distance ?? null,
    language: msg.language || prev?.language || null,
    answered: !!(prev?.answered || ANSWERED.has(msg.status) || (prev?.status === 'answered')),
    updatedAt: at,
  };
  let next = { ...em, donors: { ...em.donors, [msg.donor_id]: donor } };

  if (ACCEPTED.has(msg.status) && !next.firstAcceptAt) next.firstAcceptAt = at;

  if (msg.status === 'ringing') {
    // Calls go out concurrently: fold a burst of rings into one timeline line.
    const head = next.events[0];
    if (head && head.kind === 'calling' && at - head.at < 5000) {
      const count = head.count + 1;
      const events = [{ ...head, count, donorIds: [...(head.donorIds || []), donor.id], title: `Sarvam AI calling ${count} donors concurrently` }, ...next.events.slice(1)];
      return { ...next, events };
    }
    return pushEvent(next, {
      at, tone: 'violet', kind: 'calling', count: 1, channel: 'VOICE', donorIds: [donor.id],
      title: `Sarvam AI calling ${donor.name}`,
      sub: `${langName(donor.language)} voice${donor.distance != null ? ` · ${donor.distance.toFixed(1)} km away` : ''}`,
    });
  }
  const event = donorEvent(donor, msg.status, at, donor.eta);
  return event ? pushEvent(next, { ...event, donorId: donor.id }) : next;
}

function fromServerDispatch(d) {
  const donors = {};
  (d.donors || []).forEach((x) => {
    donors[x.donor_id] = {
      id: x.donor_id, name: x.name, status: x.status, eta: x.eta_minutes, distance: x.distance_km,
      language: x.language, answered: ANSWERED.has(x.status), updatedAt: Date.now(),
    };
  });
  const em = newEmergency(d.dispatch_id, {
    bloodGroup: d.blood_group, units: d.units || 1, urgency: d.urgency || 'urgent', address: d.address || '',
    createdAt: toMs(d.created_at), matched: (d.donors || []).length, donors, restored: true,
  });
  return pushEvent(em, { at: Date.now(), tone: 'muted', kind: 'system', title: 'Restored live state from server', sub: `${em.matched} donors in this request` });
}

function fromServerHistory(d) {
  return {
    id: d.dispatch_id, bloodGroup: d.blood_group, units: d.units, urgency: d.urgency,
    createdAt: toMs(d.created_at),
    firstAcceptAt: d.first_accept_at ? toMs(d.first_accept_at) : null,
    closedAt: d.closed_at ? toMs(d.closed_at) : null,
    matched: d.matched, contacted: d.contacted, answered: d.answered, accepted: d.accepted, donated: d.donated,
    status: d.status,
  };
}

function historyRecord(em) {
  const sm = summarize(em);
  return {
    id: em.id, bloodGroup: em.bloodGroup, units: em.units, urgency: em.urgency, patient: em.patient,
    createdAt: em.createdAt, firstAcceptAt: em.firstAcceptAt, closedAt: em.closedAt,
    matched: em.matched, contacted: sm.contacted, answered: sm.answered, accepted: sm.accepted, donated: sm.donated,
    status: em.fulfilled ? 'fulfilled' : em.closed ? (sm.donated > 0 ? 'partial' : 'closed') : 'active',
  };
}

// ── The hook ─────────────────────────────────────────────────────

export function useDispatchStore() {
  const [booting, setBooting] = useState(true);
  const [profile, setProfile] = useState(null);
  const [emergencies, setEmergencies] = useState({});
  const [selectedId, setSelectedId] = useState(null);
  const [history, setHistory] = useState([]);
  const [wsState, setWsState] = useState('offline'); // offline | connecting | live
  const [health, setHealth] = useState(null);
  const [availability, setAvailability] = useState({ status: 'idle', data: null, error: null });
  const [notice, setNotice] = useState(null);
  const [now, setNow] = useState(Date.now());

  const ws = useRef(null);
  const retry = useRef({ attempts: 0, timer: null, stopped: false });
  const profileRef = useRef(null);
  profileRef.current = profile;

  // One clock for every live timer on screen.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // ── HTTP ───────────────────────────────────────────────────────
  const request = useCallback(async (path, { method = 'GET', body, form, auth = true } = {}) => {
    const headers = {};
    if (auth && profileRef.current?.token) headers.Authorization = `Bearer ${profileRef.current.token}`;
    let payload;
    if (form) {
      headers['Content-Type'] = 'application/x-www-form-urlencoded';
      payload = new URLSearchParams(form).toString();
    } else if (body) {
      headers['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }
    const res = await fetch(`${API_URL}${path}`, { method, headers, body: payload });
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (res.status === 401 && auth && profileRef.current) {
      await clearSession('Your session expired. Please sign in again.');
    }
    if (!res.ok) {
      const detail = data?.detail;
      const message = Array.isArray(detail) ? detail.map((d) => d.msg).join(', ') : detail || `Request failed (${res.status})`;
      const err = new Error(message);
      err.status = res.status;
      throw err;
    }
    return data;
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Session ────────────────────────────────────────────────────
  const clearSession = useCallback(async (message) => {
    retry.current.stopped = true;
    if (retry.current.timer) clearTimeout(retry.current.timer);
    if (ws.current) ws.current.close();
    await AsyncStorage.removeItem(USER_KEY);
    setProfile(null);
    setEmergencies({});
    setSelectedId(null);
    setHistory([]);
    setAvailability({ status: 'idle', data: null, error: null });
    if (message) setNotice(message);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const saved = await AsyncStorage.getItem(USER_KEY);
        if (saved) {
          const user = JSON.parse(saved);
          delete user.password_hash; // older builds stored the hash; never keep it
          setProfile(user);
        }
      } catch (e) { /* ignore corrupt storage */ }
      setBooting(false);
    })();
  }, []);

  const login = useCallback(async (hospitalId, password) => {
    const id = hospitalId.trim().toUpperCase();
    const data = await request('/api/auth/token', { method: 'POST', form: { username: id, password }, auth: false });
    const user = { ...data.user, id: data.user?.id || id, token: data.access_token };
    delete user.password_hash;
    await AsyncStorage.setItem(USER_KEY, JSON.stringify(user));
    setNotice(null);
    setProfile(user);
    return user;
  }, [request]);

  const register = useCallback(async ({ name, location, phone, password }) => {
    const data = await request('/api/auth/register', { method: 'POST', body: { name, location, phone, password }, auth: false });
    return data.id;
  }, [request]);

  const logout = useCallback(() => clearSession(null), [clearSession]);

  // ── Emergencies ────────────────────────────────────────────────
  const update = useCallback((id, fn) => {
    setEmergencies((all) => {
      const current = all[id] || newEmergency(id);
      return { ...all, [id]: fn(current) };
    });
  }, []);

  const handleMessage = useCallback((raw) => {
    let msg;
    try { msg = JSON.parse(raw); } catch (e) { return; }
    if (!msg || msg.type === 'pong') return;
    if (msg.type === 'auth_ok') { retry.current.attempts = 0; setWsState('live'); return; }
    if (msg.type === 'auth_error') return; // the close handler signs the user out

    setEmergencies((all) => {
      // Older backends omit dispatch_id: attach to the newest open emergency.
      let id = msg.dispatch_id;
      if (!id || id === 'global') {
        const open = Object.values(all).filter((e) => !e.closed).sort((a, b) => b.createdAt - a.createdAt);
        id = open[0]?.id;
      }
      if (!id) return all;
      const em = all[id] || newEmergency(id);
      const at = toMs(msg.timestamp);
      let next = em;
      if (msg.type === 'dispatch_fulfilled') {
        next = pushEvent({ ...em, closed: true, fulfilled: true, closedAt: at },
          { at, tone: 'green', kind: 'fulfilled', title: 'Request fulfilled', sub: `${em.units} of ${em.units} units donated` });
      } else if (msg.type === 'dispatch_closed') {
        next = em.closed ? em : pushEvent({ ...em, closed: true, closedAt: at },
          { at, tone: 'muted', kind: 'system', title: 'Request closed by hospital', sub: 'No further calls will be placed' });
      } else if (msg.type === 'error') {
        next = pushEvent(em, { at, tone: 'red', kind: 'error', title: 'Dispatch pipeline error', sub: msg.message || 'Unknown error' });
      } else if (msg.donor_id && msg.status) {
        next = applyDonorUpdate(em, msg);
      }
      return next === em ? all : { ...all, [id]: next };
    });
  }, []);

  const connect = useCallback(() => {
    if (ws.current && (ws.current.readyState === 0 || ws.current.readyState === 1)) return;
    retry.current.stopped = false;
    setWsState('connecting');
    let socket;
    try {
      socket = new WebSocket(WS_URL);
    } catch (e) {
      setWsState('offline');
      return;
    }
    ws.current = socket;
    let heartbeat = null;
    socket.onopen = () => {
      // First message authenticates; the server confirms with auth_ok.
      socket.send(JSON.stringify({ type: 'auth', token: profileRef.current?.token || '' }));
      heartbeat = setInterval(() => { try { socket.send('ping'); } catch (e) { /* closed */ } }, 25000);
    };
    socket.onmessage = (event) => handleMessage(event.data);
    socket.onclose = (event) => {
      if (heartbeat) clearInterval(heartbeat);
      setWsState('offline');
      if (event && event.code === 4401) {
        clearSession('Your session expired. Please sign in again.');
        return;
      }
      if (retry.current.stopped) return;
      const delay = Math.min(1000 * 2 ** retry.current.attempts, 30000);
      retry.current.attempts += 1;
      retry.current.timer = setTimeout(connect, delay);
    };
    socket.onerror = () => { /* onclose follows and schedules the retry */ };
  }, [handleMessage, clearSession]);

  const refreshActive = useCallback(async () => {
    try {
      const data = await request('/api/dispatches/active');
      setEmergencies((all) => {
        const next = { ...all };
        data.dispatches.forEach((d) => {
          // Keep a local copy if we have one: it holds the richer timeline.
          if (!next[d.dispatch_id]) next[d.dispatch_id] = fromServerDispatch(d);
        });
        return next;
      });
    } catch (e) { /* dashboard still works from the live feed */ }
  }, [request]);

  const refreshAvailability = useCallback(async () => {
    setAvailability((a) => ({ ...a, status: 'loading' }));
    try {
      const data = await request('/api/network/availability');
      setAvailability({ status: 'ready', data, error: null });
    } catch (e) {
      setAvailability({ status: 'error', data: null, error: e.message });
    }
  }, [request]);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await request('/api/health', { auth: false }));
    } catch (e) {
      setHealth({ status: 'unreachable' });
    }
  }, [request]);

  // Server history is the source of truth for analytics; the local copy
  // only fills in what the server does not keep (patient reference).
  const refreshHistory = useCallback(async (days = 90) => {
    try {
      const data = await request(`/api/dispatches/history?days=${days}`);
      setHistory((prev) => {
        const local = Object.fromEntries(prev.map((h) => [h.id, h]));
        const merged = { ...local };
        data.dispatches.forEach((d) => {
          const mine = local[d.dispatch_id] || {};
          const live = mine.status === 'active' && d.status === 'active';
          merged[d.dispatch_id] = live ? { ...fromServerHistory(d), ...mine } : { ...mine, ...fromServerHistory(d), patient: mine.patient };
        });
        const next = Object.values(merged).sort((a, b) => b.createdAt - a.createdAt).slice(0, 500);
        if (profileRef.current) AsyncStorage.setItem(historyKey(profileRef.current.id), JSON.stringify(next)).catch(() => {});
        return next;
      });
    } catch (e) { /* keep showing the local copy */ }
  }, [request]);

  // Everything that starts when a hospital signs in.
  useEffect(() => {
    if (!profile) return undefined;
    connect();
    refreshActive();
    refreshAvailability();
    refreshHealth();
    const healthTimer = setInterval(refreshHealth, 30000);
    (async () => {
      try {
        const saved = await AsyncStorage.getItem(historyKey(profile.id));
        if (saved) setHistory(JSON.parse(saved));
      } catch (e) { /* ignore */ }
      refreshHistory();
    })();
    return () => {
      clearInterval(healthTimer);
      retry.current.stopped = true;
      if (retry.current.timer) clearTimeout(retry.current.timer);
      if (ws.current) ws.current.close();
    };
  }, [profile?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep request history in step with live emergencies.
  useEffect(() => {
    if (!profile) return;
    const ems = Object.values(emergencies).filter((e) => e.bloodGroup);
    if (!ems.length) return;
    setHistory((prev) => {
      const byId = Object.fromEntries(prev.map((h) => [h.id, h]));
      ems.forEach((em) => { byId[em.id] = { ...(byId[em.id] || {}), ...historyRecord(em) }; });
      const next = Object.values(byId).sort((a, b) => b.createdAt - a.createdAt).slice(0, 500);
      AsyncStorage.setItem(historyKey(profile.id), JSON.stringify(next)).catch(() => {});
      return next;
    });
  }, [emergencies, profile]);

  // Keep a sensible selection.
  const ordered = useMemo(
    () => Object.values(emergencies).sort((a, b) => (a.closed - b.closed) || (b.createdAt - a.createdAt)),
    [emergencies],
  );
  useEffect(() => {
    if (!selectedId || !emergencies[selectedId]) setSelectedId(ordered[0]?.id || null);
  }, [ordered, selectedId, emergencies]);

  // ── Actions ────────────────────────────────────────────────────
  const triggerDispatch = useCallback(async ({ patient, bloodGroup, units, urgency, address }) => {
    const data = await request('/api/dispatch', {
      method: 'POST',
      body: {
        hospital_id: profileRef.current?.id, blood_group: bloodGroup, urgency,
        coordinates: { lat: 0, lng: 0 }, address, patient_name: patient || null, units,
      },
    });
    if (!data.donors_matched) return { matched: 0, message: data.message };
    const createdAt = toMs(data.created_at);
    update(data.dispatch_id, (em) => {
      let next = {
        ...em, bloodGroup, units, urgency, address, patient, createdAt, matched: data.donors_matched,
      };
      next = pushEvent(next, { at: createdAt, tone: 'red', kind: 'trigger', title: 'Emergency triggered', sub: `${bg(bloodGroup)} × ${units} unit${units > 1 ? 's' : ''} · ${urgency}` });
      next = pushEvent(next, { at: createdAt + 1, tone: 'violet', kind: 'match', title: `${data.donors_matched} compatible donors matched`, sub: 'Graph match · blood group, 10 km, 56-day cooldown' });
      // Keep any ringing events that raced ahead of this response on top.
      next.events.sort((a, b) => b.at - a.at);
      return next;
    });
    setSelectedId(data.dispatch_id);
    return { matched: data.donors_matched, id: data.dispatch_id };
  }, [request, update]);

  const markDonated = useCallback(async (emergencyId, donorId) => {
    await request('/api/donate', {
      method: 'POST',
      body: { donor_id: donorId, hospital_id: profileRef.current?.id, dispatch_id: emergencyId, notes: 'Logged from dashboard' },
    });
  }, [request]);

  const closeEmergency = useCallback(async (emergencyId) => {
    await request(`/api/dispatches/${emergencyId}/close`, { method: 'POST' });
    update(emergencyId, (em) => (em.closed ? em : pushEvent({ ...em, closed: true, closedAt: Date.now() },
      { at: Date.now(), tone: 'muted', kind: 'system', title: 'Request closed by hospital', sub: 'No further calls will be placed' })));
  }, [request, update]);

  return {
    booting, profile, login, register, logout, notice, setNotice,
    emergencies, ordered, selectedId, setSelectedId, selected: selectedId ? emergencies[selectedId] : null,
    history, wsState, health, availability, now,
    triggerDispatch, markDonated, closeEmergency, refreshAvailability, refreshHistory, reconnect: connect,
  };
}
