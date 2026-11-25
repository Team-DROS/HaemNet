import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import {
  View, Text, TextInput, TouchableOpacity, ScrollView, ActivityIndicator, StyleSheet,
  Linking, Image, Alert, RefreshControl, AppState, StatusBar,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import * as Location from 'expo-location';
import * as ImagePicker from 'expo-image-picker';
import { bg, palette, mono, radius, shadow } from './theme';
import { API_URL, LEGAL_LINKS, REQUEST_TIMEOUT_MS } from './config';
import { PAUSE_OPTIONS, callsStatus, pauseState } from './availability';
import { connectionState, minutesSince, profileView, readSavedRequests, serializeRequests } from './network';
import { clearSession, loadSession, saveSession } from './session';
import {
  callsConsentField, codeErrorMessage, consentRequired, digitsOnly, isValidCode, registerBody, resendCountdown,
} from './donorAuth';
import { listenForAlerts, listenForAlertTaps, setUpAlerts } from './push';
import { alertTarget, tokenUpdate } from './pushLogic';
import { HEALTH_QUESTIONS, evaluateAnswers } from './eligibility';
import { APP_LANGUAGES, DEFAULT_LANGUAGE, appLanguageForCall, isAppLanguage, makeT } from './i18n';

const ThemeContext = createContext(null);
// { t, language, setLanguage }: the app's text in the donor's chosen language (see i18n.js).
const I18nContext = createContext({
  t: makeT(DEFAULT_LANGUAGE), language: DEFAULT_LANGUAGE, setLanguage: () => {}, adoptIfUnset: () => {},
});
const LANGUAGE_KEY = '@haemnet_language';

const COOLDOWN_DAYS = 56;
const MS_IN_A_DAY = 24 * 60 * 60 * 1000;
const POLL_MS = 15000;
const WAKE_TIMEOUT_MS = REQUEST_TIMEOUT_MS; // Render free instances can take a minute to wake.

const BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-', 'Others'];
// The AI voice agent speaks these three languages. Anything else falls back to English on the server.
const LANGUAGES = ['English', 'Hindi', 'Tamil'];

// Resolved once in config.js: EXPO_PUBLIC_API_URL in development, and never
// localhost or plain HTTP in a release build.
const SERVER_BASE_URL = API_URL;

const withCountryCode = (p) => (p.startsWith('+91') ? p : `+91${p}`);
const MIN_PASSWORD = 8;
const localDigits = (p) => (p || '').replace(/^\+91/, '').replace(/[^0-9]/g, '').slice(-10);

// Server timestamps are UTC; older rows may lack the zone suffix.
function parseUtc(value) {
  if (!value) return NaN;
  const str = String(value);
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(str) ? str : `${str}Z`).getTime();
}

function minutesAgo(value, t) {
  const time = parseUtc(value);
  if (Number.isNaN(time)) return null;
  const mins = Math.max(0, Math.round((Date.now() - time) / 60000));
  if (mins < 1) return t('common.justNow');
  if (mins < 60) return t('common.minAgo', { minutes: mins });
  return t('common.hoursAgo', { hours: Math.floor(mins / 60) });
}

// Permission denied for good ("don't ask again"): the only way back is Settings.
function explainBlockedPermission(t, title, message) {
  Alert.alert(title, message, [
    { text: t('common.notNow'), style: 'cancel' },
    { text: t('common.openSettings'), onPress: () => Linking.openSettings().catch(() => {}) },
  ]);
}

function openDirections(target) {
  const dest = target.lat && target.lng ? `${target.lat},${target.lng}` : encodeURIComponent(target.address || target.hospital_name || '');
  Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${dest}`);
}

export default function DonorApp() {
  const [theme, setTheme] = useState('light');
  useEffect(() => {
    AsyncStorage.getItem('@haemnet_theme').then((saved) => {
      if (saved === 'dark') setTheme('dark');
    }).catch(() => {});
  }, []);
  const toggleTheme = () => setTheme((current) => {
    const next = current === 'dark' ? 'light' : 'dark';
    AsyncStorage.setItem('@haemnet_theme', next).catch(() => {});
    return next;
  });
  const values = useMemo(() => {
    const color = palette(theme);
    return { color, s: createStyles(color) };
  }, [theme]);

  const [language, setLanguageState] = useState(DEFAULT_LANGUAGE);
  // True once the donor picked a language on this phone; until then the app follows their call language.
  const chosen = useRef(false);
  useEffect(() => {
    AsyncStorage.getItem(LANGUAGE_KEY).then((saved) => {
      if (isAppLanguage(saved)) { chosen.current = true; setLanguageState(saved); }
    }).catch(() => {});
  }, []);
  const i18n = useMemo(() => ({
    t: makeT(language),
    language,
    setLanguage: (next) => {
      if (!isAppLanguage(next)) return;
      chosen.current = true;
      setLanguageState(next);
      AsyncStorage.setItem(LANGUAGE_KEY, next).catch(() => {});
    },
    adoptIfUnset: (next) => { if (!chosen.current && isAppLanguage(next)) setLanguageState(next); },
  }), [language]);

  return (
    <ThemeContext.Provider value={values}>
      <I18nContext.Provider value={i18n}>
        <StatusBar barStyle={theme === 'dark' ? 'light-content' : 'dark-content'} backgroundColor={values.color.surface} />
        <DonorExperience theme={theme} onToggleTheme={toggleTheme} />
      </I18nContext.Provider>
    </ThemeContext.Provider>
  );
}

function DonorExperience({ theme, onToggleTheme }) {
  const { color, s } = useContext(ThemeContext);
  const { t, adoptIfUnset } = useContext(I18nContext);
  // ─── AUTHENTICATION STATE ───
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [currentUser, setCurrentUser] = useState(null); // { id: 10-digit phone, token }
  const [authMode, setAuthMode] = useState('login'); // 'login' | 'register'
  const [loginId, setLoginId] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [authError, setAuthError] = useState('');
  const [authNotice, setAuthNotice] = useState('');
  const [authLoading, setAuthLoading] = useState(false);
  // Phone verification: the server says whether a texted code is needed to create an account.
  const [otpRequired, setOtpRequired] = useState(false);
  const [otpSentAt, setOtpSentAt] = useState(null);
  const [otpCode, setOtpCode] = useState('');
  const [otpBusy, setOtpBusy] = useState(false);
  const [resendIn, setResendIn] = useState(0);

  // ─── PROFILE STATE ───
  const [name, setName] = useState('');
  const [phone, setPhone] = useState(''); // 10 local digits, no country code
  const [bloodGroup, setBloodGroup] = useState('O+');
  const [customBloodGroup, setCustomBloodGroup] = useState('');
  const [language, setLanguage] = useState('English');
  const [lat, setLat] = useState(null);
  const [lng, setLng] = useState(null);
  const [address, setAddress] = useState('');
  const [locationSource, setLocationSource] = useState(null); // 'gps' | 'manual' | null
  const [profilePic, setProfilePic] = useState(null);

  const [isRegistered, setIsRegistered] = useState(false);
  // First profile load after sign-in, and whether it failed with nothing saved to show instead.
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileUnreachable, setProfileUnreachable] = useState(false);
  const [profileFromPhone, setProfileFromPhone] = useState(false); // showing saved details, server not reached
  const [isSaving, setIsSaving] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [regError, setRegError] = useState('');
  // Consent to automated emergency calls (asked when joining) and the donor's pause switch.
  const [callsConsent, setCallsConsent] = useState(false);
  const [callsOptOut, setCallsOptOut] = useState(false);
  const [callsPausedUntil, setCallsPausedUntil] = useState(null); // ISO time a short break ends
  const [callsBusy, setCallsBusy] = useState(false);

  const [locationLoading, setLocationLoading] = useState(false);
  const [locationError, setLocationError] = useState('');

  const [lastDonatedDate, setLastDonatedDate] = useState(null);
  const [daysRemaining, setDaysRemaining] = useState(0);
  const [daysElapsed, setDaysElapsed] = useState(0);
  const [progressPercent, setProgressPercent] = useState(100);
  const [refreshing, setRefreshing] = useState(false);

  // ─── DONATION LOG STATE ───
  const [donationLog, setDonationLog] = useState([]);

  // ─── LIVE REQUESTS ───
  const [requests, setRequests] = useState([]);
  const [requestsError, setRequestsError] = useState('');
  const [requestsSavedAt, setRequestsSavedAt] = useState(null); // set while showing requests saved earlier

  // ─── CONNECTION ───
  const [connection, setConnection] = useState('unknown'); // 'online' | 'offline' | 'unknown'
  useEffect(() => NetInfo.addEventListener((state) => setConnection(connectionState(state))), []);
  const [responding, setResponding] = useState(null); // dispatch_id being answered
  const [respondMsg, setRespondMsg] = useState('');
  const [activeTrip, setActiveTrip] = useState(null); // accepted request the donor is travelling to
  const [highlightId, setHighlightId] = useState(null); // request opened from a push alert
  // Health check shown on a request card before the donor can say yes.
  const [checkingId, setCheckingId] = useState(null);
  const [answers, setAnswers] = useState({});

  // ─── PUSH ALERTS ───
  // 'on' | 'off' | 'blocked' | 'pending' | 'unsupported'; see pushLogic.alertState.
  const [alertsState, setAlertsState] = useState('off');
  const [alertsBusy, setAlertsBusy] = useState(false);
  const scrollRef = useRef(null);

  // Once, at start-up: restore a saved session.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { checkLoginStatus(); }, []);
  // Intentionally keyed on the session only: reload the profile when the donor signs in, not on every render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (isLoggedIn && currentUser) loadProfile(); }, [isLoggedIn, currentUser]);
  // Recalculate only when the last donation date changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { calculateCooldown(); }, [lastDonatedDate]);
  useEffect(() => {
    // Ask the server whether sign-up needs a texted code. If it cannot be reached, assume not;
    // the server still enforces the rule and the error message tells the donor what to do.
    axios.get(`${SERVER_BASE_URL}/api/donor/auth/config`, { timeout: WAKE_TIMEOUT_MS })
      .then((res) => setOtpRequired(Boolean(res.data?.otp_required)))
      .catch(() => setOtpRequired(false));
  }, []);
  useEffect(() => {
    if (!otpSentAt) return undefined;
    const tick = () => setResendIn(resendCountdown(otpSentAt, Date.now()));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [otpSentAt]);

  // ─── AUTHENTICATION ───
  // Donors create an account with their phone number and a password, then
  // sign in with the same pair. The server returns a donor token that every
  // donor endpoint requires.
  const userRef = useRef(null);
  userRef.current = currentUser;

  const api = async (method, path, data) => {
    const token = userRef.current?.token;
    try {
      return await axios({
        method, url: `${SERVER_BASE_URL}${path}`, data,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        timeout: WAKE_TIMEOUT_MS,
      });
    } catch (err) {
      if (err.response?.status === 401 && token) {
        await handleLogout(t('auth.sessionExpired'));
      }
      throw err;
    }
  };

  const checkLoginStatus = async () => {
    try {
      // Secure storage, migrating sessions saved in plain storage by v1.1 and earlier.
      const session = await loadSession();
      if (session) {
        setCurrentUser(session);
        setIsLoggedIn(true);
      }
    } catch {
      Alert.alert(t('auth.signInTitle'), t('auth.statusFailed'));
    }
  };

  const serverError = (err, fallback) => {
    const status = err.response?.status;
    const detail = err.response?.data?.detail;
    if (typeof detail === 'string' && detail.length < 200) return detail;
    if (!err.response) {
      return err.code === 'ECONNABORTED'
        ? t('error.slow')
        : t('error.noConnection');
    }
    if (status === 429) return t('error.tooMany');
    if (status >= 500) return t('error.server');
    return fallback;
  };

  const switchAuthMode = (mode) => {
    setAuthMode(mode);
    setAuthError(''); setAuthNotice('');
    setPassword(''); setConfirmPassword('');
    setOtpSentAt(null); setOtpCode(''); setResendIn(0);
  };

  const sendCode = async () => {
    setAuthError(''); setAuthNotice('');
    if (loginId.length !== 10) return setAuthError(t('auth.enterPhone'));
    setOtpBusy(true);
    try {
      await axios.post(`${SERVER_BASE_URL}/api/donor/auth/otp/request`, { phone: loginId }, { timeout: WAKE_TIMEOUT_MS });
      setOtpSentAt(Date.now()); setOtpCode('');
      setAuthNotice(t('auth.codeSent', { phone: loginId }));
    } catch (err) {
      setAuthError(codeErrorMessage(err, 'send'));
    }
    setOtpBusy(false);
  };

  const submitAuth = async () => {
    setAuthError(''); setAuthNotice('');
    if (loginId.length !== 10) return setAuthError(t('auth.enterPhone'));
    if (authMode === 'register') {
      if (password.length < MIN_PASSWORD) return setAuthError(t('auth.passwordShort', { min: MIN_PASSWORD }));
      if (password !== confirmPassword) return setAuthError(t('auth.passwordMismatch'));
      if (otpRequired && !otpSentAt) return setAuthError(t('auth.sendCodeFirst'));
      if (otpRequired && !isValidCode(otpCode)) return setAuthError(t('auth.enterCode'));
    } else if (!password) {
      return setAuthError(t('auth.enterPassword'));
    }
    setAuthLoading(true);
    let otpToken = null;
    try {
      if (authMode === 'register' && otpRequired) {
        try {
          const proof = await axios.post(`${SERVER_BASE_URL}/api/donor/auth/otp/verify`,
            { phone: loginId, code: otpCode.trim() }, { timeout: WAKE_TIMEOUT_MS });
          otpToken = proof.data?.otp_token;
        } catch (err) {
          setAuthError(codeErrorMessage(err, 'verify'));
          setAuthLoading(false);
          return;
        }
      }
      const path = authMode === 'register' ? 'register' : 'login';
      const body = authMode === 'register' ? registerBody(loginId, password, otpToken) : { phone: loginId, password };
      const res = await axios.post(`${SERVER_BASE_URL}/api/donor/auth/${path}`, body, { timeout: WAKE_TIMEOUT_MS });
      const session = { id: localDigits(res.data?.phone), token: res.data?.access_token };
      if (!session.token || session.id.length !== 10) throw new Error('Unexpected sign-in response');
      await saveSession(session);
      setPassword(''); setConfirmPassword(''); setAuthNotice('');
      setCurrentUser(session);
      setIsLoggedIn(true);
    } catch (err) {
      if (err.response?.status === 409) {
        setAuthMode('login'); setConfirmPassword('');
        setAuthNotice(t('auth.numberExists'));
      } else {
        setAuthError(serverError(err, authMode === 'register' ? t('auth.createFailed') : t('auth.signInFailed')));
      }
    }
    setAuthLoading(false);
  };

  const handleLogout = async (message) => {
    const session = userRef.current;
    if (session && typeof message !== 'string') forgetPushToken(session);
    if (session) AsyncStorage.removeItem(requestsKey(session.id)).catch(() => {});
    await clearSession();
    setIsLoggedIn(false);
    setCurrentUser(null);
    setLoginId('');
    setPassword(''); setConfirmPassword('');
    setAuthMode('login');
    setIsRegistered(false);
    setRequests([]);
    setActiveTrip(null);
    setHighlightId(null);
    setRequestsSavedAt(null); setProfileUnreachable(false); setProfileFromPhone(false);
    setAuthNotice(typeof message === 'string' ? message : '');
  };

  // ─── PUSH ALERTS ───
  const pushKey = (id) => `@donor_push_${id}`;

  // Register this phone for request alerts, or tell the server it no longer has a token.
  // Runs after the donor joins and whenever the app returns to the foreground; tokens can rotate.
  const syncAlerts = async (ask) => {
    const session = userRef.current;
    if (!session) return;
    const { state, token } = await setUpAlerts({ ask });
    setAlertsState(state);
    try {
      const saved = await AsyncStorage.getItem(pushKey(session.id));
      const { needed, token: next } = tokenUpdate(saved, token);
      if (!needed) return;
      await api('post', '/api/donor/push-token', { token: next });
      if (next) await AsyncStorage.setItem(pushKey(session.id), next);
      else await AsyncStorage.removeItem(pushKey(session.id));
    } catch {
      // Kept for the next launch. The automated call still reaches the donor without it.
    }
  };

  const turnOnAlerts = async () => {
    if (alertsState === 'blocked') {
      explainBlockedPermission(t, t('alerts.blockedTitle'), t('alerts.blockedBody'));
      return;
    }
    setAlertsBusy(true);
    await syncAlerts(true);
    setAlertsBusy(false);
  };

  // On sign-out the phone stops receiving this donor's alerts. Best-effort and not awaited,
  // so signing out never waits on a sleeping server.
  const forgetPushToken = (session) => {
    AsyncStorage.getItem(pushKey(session.id)).then((saved) => {
      if (!saved) return;
      AsyncStorage.removeItem(pushKey(session.id)).catch(() => {});
      axios.post(`${SERVER_BASE_URL}/api/donor/push-token`, { token: null },
        { headers: { Authorization: `Bearer ${session.token}` }, timeout: 10000 }).catch(() => {});
    }).catch(() => {});
  };

  // ─── PROFILE LOGIC ───
  const getProfileKey = () => `@donor_profile_${currentUser.id}`;
  const getLogKey = () => `@donor_log_${currentUser.id}`;
  const getTripKey = () => `@donor_trip_${currentUser.id}`;
  const requestsKey = (id) => `@donor_requests_${id}`;

  const loadProfile = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    setProfileUnreachable(false);
    try {
      const savedProfile = await AsyncStorage.getItem(getProfileKey());
      // A profile saved on this phone exists only after a successful sign-up, so show it at once
      // and let the server answer correct it. Without one, show a loading card, never the join form.
      if (savedProfile) setIsRegistered(true);
      else if (!isRefresh) setProfileLoading(true);
      if (savedProfile) {
        const profile = JSON.parse(savedProfile);
        setName(profile.name || '');
        setPhone(localDigits(profile.phone));
        const loadedBg = profile.blood_group || 'O+';
        if (BLOOD_GROUPS.includes(loadedBg) && loadedBg !== 'Others') {
          setBloodGroup(loadedBg);
          setCustomBloodGroup('');
        } else {
          setBloodGroup('Others');
          setCustomBloodGroup(loadedBg);
        }

        setLanguage(LANGUAGES.includes(profile.language) ? profile.language : 'English');
        adoptIfUnset(appLanguageForCall(profile.language));
        setLat(profile.lat != null && Number.isFinite(Number(profile.lat)) ? Number(profile.lat) : null);
        setLng(profile.lng != null && Number.isFinite(Number(profile.lng)) ? Number(profile.lng) : null);
        setAddress(profile.address || '');
        setLocationSource(profile.location_source || null);
        setProfilePic(profile.profilePic || null);
        if (profile.last_donated_date) {
          setLastDonatedDate(new Date(profile.last_donated_date));
        }
      } else {
        // Reset state for new user; the login number doubles as the donor phone.
        setName(''); setPhone(localDigits(currentUser.id)); setBloodGroup('O+'); setCustomBloodGroup(''); setLanguage('English');
        setLat(null); setLng(null); setAddress(''); setLocationSource(null);
        setProfilePic(null); setLastDonatedDate(null); setIsRegistered(false);
      }

      const savedTrip = await AsyncStorage.getItem(getTripKey());
      setActiveTrip(savedTrip ? JSON.parse(savedTrip) : null);

      const savedLog = await AsyncStorage.getItem(getLogKey());
      let currentLog = savedLog ? JSON.parse(savedLog) : [];

      // ─── SYNC WITH BACKEND ───
      try {
        const phoneParam = withCountryCode(currentUser.id);
        const response = await api('get', `/api/donor/profile/${encodeURIComponent(phoneParam)}`);
        const backendProfile = response.data.donor;

        // Returning donor on a new phone: start the form from what the network knows.
        if (backendProfile) {
          setIsRegistered(true);
          setCallsOptOut(Boolean(backendProfile.calls_opt_out));
          setCallsPausedUntil(backendProfile.calls_paused_until || null);
          setName(backendProfile.name || '');
          const serverGroup = backendProfile.blood_group || 'O+';
          if (BLOOD_GROUPS.includes(serverGroup) && serverGroup !== 'Others') {
            setBloodGroup(serverGroup);
            setCustomBloodGroup('');
          } else {
            setBloodGroup('Others');
            setCustomBloodGroup(serverGroup);
          }
        }

        if (backendProfile && backendProfile.last_donated_date) {
          const backendDate = new Date(backendProfile.last_donated_date);

          let localDate = null;
          if (savedProfile) {
            const parsedProfile = JSON.parse(savedProfile);
            if (parsedProfile.last_donated_date) {
              localDate = new Date(parsedProfile.last_donated_date);
            }
          }

          // If backend has a newer donation date, update local state
          if (!localDate || backendDate.getTime() > localDate.getTime()) {
            setLastDonatedDate(backendDate);

            if (savedProfile) {
              const updatedProfile = { ...JSON.parse(savedProfile), last_donated_date: backendProfile.last_donated_date };
              await AsyncStorage.setItem(getProfileKey(), JSON.stringify(updatedProfile));
            }

            // The trip that led to this donation is over.
            const tripRaw = await AsyncStorage.getItem(getTripKey());
            const trip = tripRaw ? JSON.parse(tripRaw) : null;
            await AsyncStorage.removeItem(getTripKey());
            setActiveTrip(null);

            const newLogEntry = {
              id: Date.now().toString(),
              date: backendProfile.last_donated_date,
              hospital: trip?.hospital_name || 'HaemNet emergency dispatch',
              status: 'Completed',
            };
            currentLog = [newLogEntry, ...currentLog];
            await AsyncStorage.setItem(getLogKey(), JSON.stringify(currentLog));
          }
        }
        if (!backendProfile) setIsRegistered(false);
        setProfileFromPhone(false);
      } catch (backendErr) {
        const server = backendErr.response?.status === 404 ? 'missing' : 'unreachable';
        const view = profileView({ hasSaved: Boolean(savedProfile), server });
        if (server === 'missing' && savedProfile) await AsyncStorage.removeItem(getProfileKey());
        // An outage never shows the join form: that would invite a duplicate sign-up.
        setIsRegistered(view === 'dashboard');
        setProfileUnreachable(view === 'retry');
        setProfileFromPhone(server === 'unreachable' && view === 'dashboard');
      }

      setDonationLog(currentLog);
    } catch {
      Alert.alert(t('common.error'), t('profile.loadFailed'));
    }
    setProfileLoading(false);
    if (isRefresh) {
      await fetchRequests();
      setRefreshing(false);
    }
  };

  const handleRegister = async () => {
    setRegError('');
    if (!name.trim()) return setRegError(t('reg.nameRequired'));
    if (!phone.trim()) return setRegError(t('reg.phoneRequired'));
    if (phone.length !== 10) return setRegError(t('reg.phoneDigits'));
    if (!locationSource || !Number.isFinite(lat) || !Number.isFinite(lng)) {
      return setRegError(t('reg.locationRequired'));
    }

    const finalBloodGroup = bloodGroup === 'Others' ? customBloodGroup.trim() : bloodGroup;
    if (!finalBloodGroup) return setRegError(t('reg.groupRequired'));
    if (consentRequired(isRegistered) && !callsConsent) {
      return setRegError(t('reg.consentRequired'));
    }

    const finalPhone = withCountryCode(currentUser.id); // always the number the donor signed in with

    setIsSaving(true);
    const profile = {
      name, phone: finalPhone, blood_group: finalBloodGroup, language,
      lat, lng, address, location_source: locationSource,
      profilePic,
      last_donated_date: lastDonatedDate ? lastDonatedDate.toISOString() : null,
    };
    try {
      await api('post', '/api/donor/register', {
        name: profile.name,
        phone: profile.phone,
        blood_group: profile.blood_group,
        language: profile.language,
        lat: profile.lat,
        lng: profile.lng,
        ...callsConsentField(isRegistered, callsConsent),
      });
      await AsyncStorage.setItem(getProfileKey(), JSON.stringify(profile));
      adoptIfUnset(appLanguageForCall(profile.language));
      setIsSaving(false); setIsRegistered(true); setIsEditing(false);
    } catch (err) {
      setIsSaving(false);
      setRegError(t('reg.saveFailed', { reason: serverError(err, t('error.serverReturned', { status: err.response?.status })) }));
    }
  };

  const toggleCalls = async () => {
    const next = !callsOptOut;
    setCallsBusy(true); setRegError('');
    try {
      await api('post', '/api/donor/calls/preference', { opt_out: next });
      setCallsOptOut(next);
    } catch (err) {
      setRegError(t('reg.callsFailed', { reason: serverError(err, t('error.tryAgain')) }));
    }
    setCallsBusy(false);
  };

  const pauseFor = async (days) => {
    setCallsBusy(true); setRegError('');
    try {
      const res = await api('post', '/api/donor/availability', { pause_days: days });
      setCallsPausedUntil(res.data?.calls_paused_until || null);
    } catch (err) {
      setRegError(t('availability.error', { reason: serverError(err, t('error.tryAgain')) }));
    }
    setCallsBusy(false);
  };

  const clearProfile = async () => {
    try {
      await api('delete', `/api/donor/profile/${encodeURIComponent(withCountryCode(currentUser.id))}`);

      await AsyncStorage.multiRemove([getProfileKey(), getLogKey(), getTripKey(), pushKey(currentUser.id), requestsKey(currentUser.id)]);
      setName(''); setPhone(localDigits(currentUser.id)); setBloodGroup('O+'); setCustomBloodGroup(''); setLanguage('English');
      setLat(null); setLng(null); setAddress(''); setLocationSource(null);
      setProfilePic(null); setLastDonatedDate(null); setDonationLog([]); setActiveTrip(null); setRequests([]);
      setIsRegistered(false); setIsEditing(false);
      Alert.alert(t('delete.done'), t('delete.doneBody'));
    } catch (err) {
      // Never log the raw error: axios errors carry request headers, including the token.
      Alert.alert(t('delete.failed'), serverError(err, t('delete.failedBody')));
    }
  };

  const confirmClearProfile = () => {
    Alert.alert(
      t('delete.title'),
      t('delete.body'),
      [
        { text: t('common.cancel'), style: 'cancel' },
        { text: t('common.delete'), style: 'destructive', onPress: clearProfile },
      ],
    );
  };

  const handleNameChange = (text) => setName(text.slice(0, 80));

  const handleLoginIdChange = (text) => {
    setLoginId(text.replace(/[^0-9]/g, '').slice(0, 10));
  };

  // ─── LIVE REQUESTS ───
  const donorPhone = isRegistered && phone ? withCountryCode(phone) : null;

  const showSavedRequests = async () => {
    const saved = readSavedRequests(await AsyncStorage.getItem(requestsKey(userRef.current?.id)).catch(() => null));
    if (saved) { setRequests(saved.requests); setRequestsSavedAt(saved.savedAt); }
    return Boolean(saved);
  };

  const fetchRequests = useCallback(async () => {
    if (!donorPhone) return;
    try {
      const res = await api('get', `/api/donor/requests/${encodeURIComponent(donorPhone)}`);
      const list = res.data.requests || [];
      setRequests(list);
      setRequestsError(''); setRequestsSavedAt(null);
      AsyncStorage.setItem(requestsKey(userRef.current?.id), serializeRequests(list)).catch(() => {});
    } catch (err) {
      if (err.response?.status === 401) return;
      // Keep what is on screen; if nothing is, fall back to the list saved on this phone.
      if (!(await showSavedRequests())) setRequestsError(t('requests.unreachable'));
    }
    // `api` reads the current token from a ref, so its changing identity does not matter here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [donorPhone]);

  // Poll while the app is in the foreground and the donor is registered.
  const appState = useRef(AppState.currentState);
  const connectionRef = useRef(connection);
  connectionRef.current = connection;
  useEffect(() => {
    if (!donorPhone || isEditing) return undefined;
    fetchRequests();
    const timer = setInterval(() => { if (appState.current === 'active' && connectionRef.current !== 'offline') fetchRequests(); }, POLL_MS);
    const sub = AppState.addEventListener('change', (next) => {
      if (appState.current !== 'active' && next === 'active') fetchRequests();
      appState.current = next;
    });
    return () => { clearInterval(timer); sub.remove(); };
  }, [donorPhone, isEditing, fetchRequests]);

  // Back online: refresh everything that may have changed, without waiting for the next poll.
  const wasOffline = useRef(false);
  useEffect(() => {
    if (connection === 'offline') { wasOffline.current = true; return; }
    if (connection !== 'online' || !wasOffline.current || !isLoggedIn) return;
    wasOffline.current = false;
    if (profileUnreachable || profileFromPhone) loadProfile();
    else fetchRef.current?.();
    // Runs on connection changes only; the loaders read current state through refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connection]);

  // Once the donor has joined, ask for alerts and keep the token fresh each time the app opens.
  useEffect(() => {
    if (!donorPhone) return undefined;
    syncAlerts(true);
    const sub = AppState.addEventListener('change', (next) => { if (next === 'active') syncAlerts(false); });
    return () => sub.remove();
    // syncAlerts reads the session from a ref; re-run only when the donor changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [donorPhone]);

  // A tap on an alert opens the app on that request; an alert while the app is open refreshes the list.
  const fetchRef = useRef(fetchRequests);
  fetchRef.current = fetchRequests;
  useEffect(() => {
    if (!isLoggedIn) return undefined;
    const stopTaps = listenForAlertTaps((response) => {
      const target = alertTarget(response);
      if (!target) return;
      setHighlightId(target.action === 'show-request' ? target.dispatchId : null);
      scrollRef.current?.scrollTo?.({ y: 0, animated: true });
      fetchRef.current();
    });
    const stopAlerts = listenForAlerts((notification) => { if (alertTarget(notification)) fetchRef.current(); });
    return () => { stopTaps(); stopAlerts(); };
  }, [isLoggedIn]);

  const startCheck = (req) => { setRespondMsg(''); setAnswers({}); setCheckingId(req.dispatch_id); };
  const stopCheck = () => { setCheckingId(null); setAnswers({}); };
  const answerQuestion = (id, value) => setAnswers((current) => ({ ...current, [id]: value }));

  const respond = async (req, accept) => {
    if (responding) return; // one answer at a time; ignores double taps
    // The health check is part of saying yes: an accept that skipped it is a bug, never sent.
    if (accept && (daysRemaining > 0 || !evaluateAnswers(answers).eligible)) return;
    setResponding(req.dispatch_id);
    setRespondMsg('');
    try {
      const res = await api('post', '/api/donor/respond', { dispatch_id: req.dispatch_id, accept });
      setRequests((list) => list.filter((r) => r.dispatch_id !== req.dispatch_id));
      if (accept) {
        const trip = { ...req, eta_minutes: res.data.eta_minutes ?? req.eta_minutes, accepted_at: new Date().toISOString() };
        setActiveTrip(trip);
        await AsyncStorage.setItem(getTripKey(), JSON.stringify(trip));
      } else {
        setRespondMsg(t('requests.declined'));
      }
    } catch (err) {
      const status = err.response?.status;
      if (status === 404 || status === 409) {
        setRequests((list) => list.filter((r) => r.dispatch_id !== req.dispatch_id));
        setRespondMsg(status === 404 ? t('requests.closed') : t('requests.alreadyAnswered'));
      } else {
        setRespondMsg(t('requests.sendFailed'));
      }
    }
    setResponding(null);
    stopCheck();
  };

  const endTrip = async () => {
    setActiveTrip(null);
    await AsyncStorage.removeItem(getTripKey());
  };

  // ─── IMAGE PICKER ───
  const pickImage = async (useCamera = false) => {
    try {
      let result;
      if (useCamera) {
        const { status, canAskAgain } = await ImagePicker.requestCameraPermissionsAsync();
        if (status !== 'granted') {
          if (canAskAgain === false) explainBlockedPermission(t, t('photo.cameraOffTitle'), t('photo.cameraOffBody'));
          else Alert.alert(t('permission.neededTitle'), t('photo.cameraNeeded'));
          return;
        }
        result = await ImagePicker.launchCameraAsync({
          mediaTypes: ['images'], allowsEditing: true, aspect: [1, 1], quality: 0.5,
        });
      } else {
        const { status, canAskAgain } = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (status !== 'granted') {
          if (canAskAgain === false) explainBlockedPermission(t, t('photo.photosOffTitle'), t('photo.photosOffBody'));
          else Alert.alert(t('permission.neededTitle'), t('photo.galleryNeeded'));
          return;
        }
        result = await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ['images'], allowsEditing: true, aspect: [1, 1], quality: 0.5,
        });
      }
      if (!result.canceled && result.assets && result.assets.length > 0) {
        setProfilePic(result.assets[0].uri);
      }
    } catch {
      Alert.alert(t('common.error'), t('photo.failed'));
    }
  };

  const promptImagePicker = () => {
    Alert.alert(t('photo.title'), t('photo.choose'), [
      { text: t('photo.take'), onPress: () => pickImage(true) },
      { text: t('photo.gallery'), onPress: () => pickImage(false) },
      { text: t('common.cancel'), style: 'cancel' },
    ]);
  };

  // ─── LOCATION HELPERS ───
  const requestLocation = async () => {
    setLocationLoading(true);
    setLocationError('');
    try {
      const { status, canAskAgain } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        setLocationError(canAskAgain === false
          ? t('loc.blocked')
          : t('loc.denied'));
        if (canAskAgain === false) explainBlockedPermission(t, t('loc.offTitle'), t('loc.offBody'));
        setLocationLoading(false);
        return;
      }
      const location = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const { latitude, longitude } = location.coords;
      setLat(latitude);
      setLng(longitude);
      // reverseGeocodeAsync can crash on Android devices without Google Play Services,
      // so the coordinates are shown directly.
      setAddress(`${latitude.toFixed(6)}, ${longitude.toFixed(6)}`);
      setLocationSource('gps');
    } catch (err) {
      setLocationError(t('loc.failed', { reason: err.message }));
    }
    setLocationLoading(false);
  };

  const clearLocation = () => {
    setLocationSource(null);
    setAddress('');
    setLocationError('');
    setLat(null);
    setLng(null);
  };

  const confirmArea = async () => {
    const query = address.trim();
    if (query.length < 6) return setLocationError(t('loc.tooShort'));
    setLocationLoading(true);
    setLocationError('');
    try {
      // Android geocoding requires foreground location permission, even when
      // the donor types the address. Never fall back to a different city.
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') throw new Error(t('loc.needPermission'));
      const matches = await Location.geocodeAsync(query);
      const point = matches?.[0];
      if (!point || !Number.isFinite(point.latitude) || !Number.isFinite(point.longitude)) {
        throw new Error(t('loc.notFound'));
      }
      setLat(point.latitude);
      setLng(point.longitude);
      setLocationSource('manual');
    } catch (err) {
      setLocationError(err.message || t('loc.findFailed'));
    } finally {
      setLocationLoading(false);
    }
  };

  // ─── COOLDOWN ───
  const calculateCooldown = () => {
    if (!lastDonatedDate) {
      setDaysRemaining(0);
      setDaysElapsed(COOLDOWN_DAYS);
      setProgressPercent(100);
      return;
    }
    const today = new Date();
    const todayMidnight = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const donationMidnight = new Date(lastDonatedDate.getFullYear(), lastDonatedDate.getMonth(), lastDonatedDate.getDate());
    const diffDays = Math.floor((todayMidnight.getTime() - donationMidnight.getTime()) / MS_IN_A_DAY);
    setDaysElapsed(diffDays);
    setDaysRemaining(Math.max(0, COOLDOWN_DAYS - diffDays));
    setProgressPercent(Math.max(0, Math.min(100, (diffDays / COOLDOWN_DAYS) * 100)));
  };

  const getNextEligibleDateText = () => {
    if (!lastDonatedDate) return '';
    const eligibleDate = new Date(lastDonatedDate.getTime());
    eligibleDate.setDate(eligibleDate.getDate() + COOLDOWN_DAYS);
    return t.date(eligibleDate);
  };

  // ─── RENDERERS ───

  if (!isLoggedIn) {
    return (
      <ScrollView style={s.root} contentContainerStyle={s.authContent} keyboardShouldPersistTaps="handled">
        <View style={[s.row, { marginBottom: 34, justifyContent: 'space-between' }]}>
          <View style={s.row}>
            <DropMark size={26} />
            <Text style={s.brand}>HaemNet</Text>
          </View>
          <ThemeSwitch theme={theme} onPress={onToggleTheme} />
        </View>

        {connection === 'offline' ? <Notice tone="amber">{t('offline.banner')}</Notice> : null}

        <LanguageSwitch style={{ marginBottom: 22 }} />

        <View style={s.authHero}>
          <Text style={s.authHeroEyebrow}>{t('auth.eyebrow')}</Text>
          <Text style={s.authHeroTitle}>{t('auth.heroTitle')}</Text>
          <Text style={s.authHeroBody}>{t('auth.heroBody')}</Text>
          <View style={s.heroSteps}>
            <Text style={s.heroStep}>{t('auth.step1')}</Text>
            <Text style={s.heroStep}>{t('auth.step2')}</Text>
            <Text style={s.heroStep}>{t('auth.step3')}</Text>
          </View>
        </View>

        <Text style={s.h1}>{authMode === 'login' ? t('auth.signInTitle') : t('auth.createTitle')}</Text>
        <Text style={s.lede}>
          {authMode === 'login'
            ? t('auth.signInLede')
            : t('auth.createLede')}
        </Text>

        {authNotice ? <Notice tone="amber">{authNotice}</Notice> : null}

        <Field label={t('auth.mobile')}>
          <View style={s.phoneRow}>
            <Text style={s.phonePrefix}>+91</Text>
            <TextInput value={loginId} onChangeText={handleLoginIdChange} placeholder="98765 43210"
              placeholderTextColor={color.faint} keyboardType="phone-pad" maxLength={10}
              autoComplete="tel" textContentType="telephoneNumber"
              style={[s.inputBare, { fontFamily: mono }]} accessibilityLabel={t('auth.mobile')} />
          </View>
        </Field>
        <Field label={t('auth.password')} hint={authMode === 'register' ? t('auth.passwordHint', { min: MIN_PASSWORD }) : null}>
          <View style={s.phoneRow}>
            <TextInput value={password} onChangeText={(v) => { setPassword(v.slice(0, 72)); if (authError) setAuthError(''); }}
              placeholder={authMode === 'register' ? t('auth.choosePassword') : t('auth.yourPassword')} placeholderTextColor={color.faint}
              secureTextEntry={!showPassword} autoCapitalize="none" autoCorrect={false}
              autoComplete={authMode === 'register' ? 'password-new' : 'password'}
              textContentType={authMode === 'register' ? 'newPassword' : 'password'}
              onSubmitEditing={authMode === 'login' ? submitAuth : undefined}
              style={s.inputBare} accessibilityLabel={t('auth.password')} />
            <TouchableOpacity onPress={() => setShowPassword((v) => !v)} accessibilityRole="button"
              accessibilityLabel={showPassword ? t('auth.hidePassword') : t('auth.showPassword')} style={{ paddingHorizontal: 14 }}>
              <Text style={s.switchLink}>{showPassword ? t('auth.hide') : t('auth.show')}</Text>
            </TouchableOpacity>
          </View>
        </Field>
        {authMode === 'register' ? (
          <Field label={t('auth.confirmPassword')}>
            <TextInput value={confirmPassword} onChangeText={(v) => { setConfirmPassword(v.slice(0, 72)); if (authError) setAuthError(''); }}
              placeholder={t('auth.typeAgain')} placeholderTextColor={color.faint}
              secureTextEntry={!showPassword} autoCapitalize="none" autoCorrect={false}
              autoComplete="password-new" textContentType="newPassword" onSubmitEditing={submitAuth}
              style={s.input} accessibilityLabel={t('auth.confirmPassword')} />
          </Field>
        ) : null}
        {authMode === 'register' && otpRequired ? (
          <Field label={t('auth.code')} hint={t('auth.codeHint')}>
            <View style={s.phoneRow}>
              <TextInput value={otpCode} onChangeText={(v) => { setOtpCode(digitsOnly(v)); if (authError) setAuthError(''); }}
                placeholder={t('auth.codePlaceholder')} placeholderTextColor={color.faint} keyboardType="number-pad" maxLength={6}
                autoComplete="sms-otp" textContentType="oneTimeCode"
                style={[s.inputBare, { fontFamily: mono }]} accessibilityLabel={t('auth.code')} />
              <TouchableOpacity onPress={sendCode} disabled={otpBusy || resendIn > 0} accessibilityRole="button"
                accessibilityLabel={t('auth.sendCodeLabel')} style={{ paddingHorizontal: 14, opacity: otpBusy || resendIn > 0 ? 0.5 : 1 }}>
                <Text style={s.switchLink}>{otpBusy ? t('auth.sending') : resendIn > 0 ? t('auth.resendIn', { seconds: resendIn }) : otpSentAt ? t('auth.resend') : t('auth.sendCode')}</Text>
              </TouchableOpacity>
            </View>
          </Field>
        ) : null}

        {authError ? <Notice tone="red">{authError}</Notice> : null}

        <PrimaryButton onPress={submitAuth} busy={authLoading} style={{ marginTop: 8 }}>
          {authMode === 'login' ? t('auth.signInButton') : t('auth.createButton')}
        </PrimaryButton>

        <View style={[s.row, { justifyContent: 'center', marginTop: 18 }]}>
          <Text style={s.switchText}>{authMode === 'login' ? t('auth.newHere') : t('auth.alreadyJoined')}</Text>
          <TouchableOpacity onPress={() => switchAuthMode(authMode === 'login' ? 'register' : 'login')} accessibilityRole="button">
            <Text style={s.switchLink}>{authMode === 'login' ? t('auth.createLink') : t('auth.signInLink')}</Text>
          </TouchableOpacity>
        </View>
        {authMode === 'login' ? (
          <Text style={[s.switchText, { textAlign: 'center', marginTop: 10, fontSize: 13 }]}>
            {t('auth.forgot')}
          </Text>
        ) : null}

        <View style={s.authFacts}>
          <Fact title={t('auth.fact1Title')} body={t('auth.fact1Body')} />
          <Fact title={t('auth.fact2Title')} body={t('auth.fact2Body')} />
          <Fact title={t('auth.fact3Title')} body={t('auth.fact3Body')} last />
        </View>
      </ScrollView>
    );
  }

  const renderLocationPicker = () => (
    <View style={{ marginTop: 18 }}>
      <Text style={s.label}>{t('loc.label')}</Text>

      {locationSource ? (
        <View style={s.locationConfirmed}>
          <View style={[s.row, { justifyContent: 'space-between', gap: 10 }]}>
            <View style={{ flex: 1 }}>
              <Text style={s.locationTag}>{locationSource === 'gps' ? t('loc.gpsSet') : t('loc.areaSet')}</Text>
              <Text style={s.locationAddr} numberOfLines={2}>{address || t('loc.set')}</Text>
            </View>
            <TouchableOpacity onPress={clearLocation} style={s.smallBtn} accessibilityRole="button">
              <Text style={s.smallBtnText}>{t('common.change')}</Text>
            </TouchableOpacity>
          </View>

          {Number.isFinite(lat) && Number.isFinite(lng) && (
            <TouchableOpacity onPress={() => Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${lat},${lng}`)}
              style={s.locationPreview} accessibilityRole="button" accessibilityLabel={t('loc.viewInMaps')}>
              <Text style={s.locationPreviewPin}>⌖</Text>
              <View style={{ flex: 1 }}>
                <Text style={s.locationPreviewTitle}>{t('loc.pinned')}</Text>
                <Text style={s.locationPreviewCoords}>{lat.toFixed(5)}, {lng.toFixed(5)} · {t('loc.viewMapsShort')}</Text>
              </View>
            </TouchableOpacity>
          )}
        </View>
      ) : (
        <View>
          <TouchableOpacity onPress={requestLocation} disabled={locationLoading} style={s.gpsBtn} activeOpacity={0.85} accessibilityRole="button">
            {locationLoading ? (
              <View style={s.row}>
                <ActivityIndicator size="small" color={color.greenText} />
                <Text style={[s.gpsBtnText, { marginLeft: 10 }]}>{t('loc.detecting')}</Text>
              </View>
            ) : (
              <View style={s.row}>
                <View style={s.gpsDot}><View style={s.gpsDotInner} /></View>
                <View style={{ marginLeft: 12 }}>
                  <Text style={s.gpsBtnText}>{t('loc.useCurrent')}</Text>
                  <Text style={s.gpsBtnSub}>{t('loc.mostAccurate')}</Text>
                </View>
              </View>
            )}
          </TouchableOpacity>

          {locationError ? <Notice tone="amber">{locationError}</Notice> : null}

          <View style={s.orRow}>
            <View style={s.orLine} />
            <Text style={s.orText}>{t('loc.orType')}</Text>
            <View style={s.orLine} />
          </View>

          <TextInput
            value={address}
            onChangeText={setAddress}
            onEndEditing={() => { if (locationSource) setLocationSource(null); }}
            placeholder="Koramangala, Bengaluru 560034"
            placeholderTextColor={color.faint}
            style={[s.input, { minHeight: 64, textAlignVertical: 'top' }]}
            multiline
            numberOfLines={2}
          />
          <SecondaryButton onPress={confirmArea} busy={locationLoading} style={{ marginTop: 10 }}>
            {locationLoading ? t('loc.finding') : t('loc.confirm')}
          </SecondaryButton>
        </View>
      )}
    </View>
  );

  const eligible = daysRemaining === 0;
  const firstName = (name || '').trim().split(/\s+/)[0];
  const displayGroup = bloodGroup === 'Others' ? customBloodGroup : bloodGroup;

  return (
    <ScrollView
      ref={scrollRef}
      style={s.root}
      contentContainerStyle={s.rootContent}
      keyboardShouldPersistTaps="handled"
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => loadProfile(true)} colors={[color.text]} tintColor={color.text2} />}
    >
      <View style={[s.row, { justifyContent: 'space-between', marginBottom: 22 }]}>
        <View style={s.row}>
          <DropMark size={22} />
          <Text style={[s.brand, { fontSize: 17 }]}>HaemNet</Text>
        </View>
        <View style={[s.row, { gap: 8 }]}>
          <ThemeSwitch theme={theme} onPress={onToggleTheme} />
          <TouchableOpacity onPress={() => handleLogout()} style={s.smallBtn} accessibilityRole="button">
            <Text style={s.smallBtnText}>{t('common.signOut')}</Text>
          </TouchableOpacity>
        </View>
      </View>

      {connection === 'offline' ? <View style={{ marginTop: -10, marginBottom: 14 }}><Notice tone="amber">{t('offline.banner')}</Notice></View> : null}

      {profileLoading && !isRegistered ? (
        <View style={[s.card, { alignItems: 'center', paddingVertical: 36 }]} accessibilityLiveRegion="polite">
          <ActivityIndicator color={color.text2} />
          <Text style={[s.cardTitle, { fontSize: 16 }]}>{t('offline.loading')}</Text>
          <Text style={[s.hint, { textAlign: 'center' }]}>{t('offline.loadingSlow')}</Text>
        </View>
      ) : profileUnreachable && !isRegistered ? (
        <View style={s.card}>
          <Text style={s.cardTitle}>{t('offline.retryTitle')}</Text>
          <Text style={s.cardDesc}>{t('offline.retryBody')}</Text>
          <PrimaryButton onPress={() => loadProfile()}>{t('offline.retry')}</PrimaryButton>
        </View>
      ) : !isRegistered || isEditing ? (
        <View style={s.card}>
          <Text style={s.overline}>{t('reg.overline')}</Text>
          <Text style={s.cardTitle}>{isEditing ? t('reg.editTitle') : t('reg.joinTitle')}</Text>
          <Text style={s.cardDesc}>{t('reg.privacyNote')}</Text>

          <View style={{ alignItems: 'center', marginBottom: 22 }}>
            <TouchableOpacity onPress={promptImagePicker} style={s.avatarLg} accessibilityRole="button" accessibilityLabel={t('reg.addPhoto')}>
              {profilePic ? (
                <Image source={{ uri: profilePic }} style={s.avatarLgImage} />
              ) : (
                <Text style={s.avatarLgInitial}>{firstName ? firstName[0].toUpperCase() : '+'}</Text>
              )}
            </TouchableOpacity>
            <Text style={s.avatarHint}>{profilePic ? t('reg.changePhoto') : t('reg.addPhotoOptional')}</Text>
          </View>

          <Field label={t('reg.fullName')}>
            <TextInput value={name} onChangeText={handleNameChange} placeholder="Ramesh Patel" placeholderTextColor={color.faint} style={s.input} />
          </Field>

          <Field label={t('reg.phone')} hint={t('reg.phoneHint')}>
            <View style={[s.phoneRow, { backgroundColor: color.surface2 }]}>
              <Text style={s.phonePrefix}>+91</Text>
              <TextInput value={phone} editable={false} style={[s.inputBare, { fontFamily: mono, color: color.text2 }]}
                accessibilityLabel={t('reg.verifiedPhone')} />
            </View>
          </Field>

          <Text style={s.label}>{t('reg.bloodGroup')}</Text>
          <View style={s.chipGrid}>
            {BLOOD_GROUPS.map((g) => {
              const active = bloodGroup === g;
              return (
                <TouchableOpacity key={g} onPress={() => setBloodGroup(g)} accessibilityRole="button" accessibilityState={{ selected: active }}
                  style={[s.groupChip, g === 'Others' && { width: '48%' }, active && s.groupChipActive]}>
                  <Text style={[s.groupChipText, active && s.groupChipTextActive]}>{g === 'Others' ? t('reg.otherGroup') : bg(g)}</Text>
                </TouchableOpacity>
              );
            })}
          </View>

          {bloodGroup === 'Others' && (
            <TextInput value={customBloodGroup} onChangeText={setCustomBloodGroup} placeholder={t('reg.otherGroupPlaceholder')}
              placeholderTextColor={color.faint} style={[s.input, { marginTop: 10 }]} />
          )}

          <Text style={[s.label, { marginTop: 18 }]}>{t('reg.callLanguage')}</Text>
          <View style={s.segmented}>
            {LANGUAGES.map((lang) => {
              const active = language === lang;
              return (
                <TouchableOpacity key={lang} onPress={() => setLanguage(lang)} accessibilityRole="button" accessibilityState={{ selected: active }}
                  style={[s.segment, active && s.segmentActive]}>
                  <Text style={[s.segmentText, active && s.segmentTextActive]}>{t(`language.${lang}`)}</Text>
                </TouchableOpacity>
              );
            })}
          </View>

          {renderLocationPicker()}

          {consentRequired(isRegistered) ? (
            <TouchableOpacity onPress={() => { setCallsConsent((v) => !v); if (regError) setRegError(''); }}
              accessibilityRole="checkbox" accessibilityState={{ checked: callsConsent }}
              accessibilityLabel={t('reg.consentLabel')} style={[s.row, { gap: 12, marginTop: 18, alignItems: 'flex-start' }]}>
              <View style={{ width: 24, height: 24, borderRadius: 6, borderWidth: 2, borderColor: callsConsent ? color.green : color.faint,
                backgroundColor: callsConsent ? color.green : 'transparent', alignItems: 'center', justifyContent: 'center' }}>
                {callsConsent ? <Text style={{ color: '#FFFFFF', fontWeight: '700' }}>✓</Text> : null}
              </View>
              <Text style={[s.hint, { flex: 1 }]}>
                {t('reg.consent')}
              </Text>
            </TouchableOpacity>
          ) : null}
          {consentRequired(isRegistered) ? (
            <TouchableOpacity onPress={() => Linking.openURL(LEGAL_LINKS.privacy).catch(() => {})} accessibilityRole="link"
              style={{ marginTop: 8, marginLeft: 36 }}>
              <Text style={s.legalLink}>{t('legal.privacy')}</Text>
            </TouchableOpacity>
          ) : null}

          {regError ? <Notice tone="red">{regError}</Notice> : null}

          <View style={[s.row, { marginTop: 22, gap: 10 }]}>
            {isEditing && (
              <SecondaryButton onPress={() => { setIsEditing(false); setRegError(''); }} style={{ flex: 1 }}>{t('common.cancel')}</SecondaryButton>
            )}
            <PrimaryButton onPress={handleRegister} busy={isSaving} style={{ flex: 2 }}>
              {isEditing ? t('reg.save') : t('reg.join')}
            </PrimaryButton>
          </View>
        </View>
      ) : (
        <View>
          <View style={s.welcomeBanner}>
            <Text style={s.welcomeEyebrow}>{t('dash.welcomeEyebrow', { group: bg(displayGroup) })}</Text>
            <Text style={s.welcomeTitle}>{t('dash.welcomeTitle')}</Text>
            <Text style={s.welcomeBody}>{t('dash.welcomeBody')}</Text>
          </View>
          <Text style={s.greeting}>{firstName ? t('dash.hi', { name: firstName }) : t('dash.hiNoName')}</Text>
          <Text style={s.greetingSub}>
            {requests.length
              ? (requests.length === 1 ? t('dash.oneNeeds') : t('dash.manyNeed', { count: requests.length }))
              : activeTrip ? t('dash.thanksYes') : eligible ? t('dash.ready') : t('dash.recoveringLine')}
          </Text>

          {requests.map((req) => (
            <RequestCard key={req.dispatch_id} req={req} busy={responding === req.dispatch_id}
              highlighted={highlightId === req.dispatch_id}
              checking={checkingId === req.dispatch_id} answers={answers} onAnswer={answerQuestion}
              recoveringDays={daysRemaining} onStartCheck={() => startCheck(req)} onStopCheck={stopCheck}
              onAccept={() => respond(req, true)} onDecline={() => respond(req, false)} />
          ))}

          {respondMsg ? <Notice tone="neutral">{respondMsg}</Notice> : null}
          {requestsSavedAt ? <Notice tone="amber">{t('offline.savedRequests', { minutes: minutesSince(requestsSavedAt) })}</Notice> : null}
          {requestsError ? <Notice tone="amber">{requestsError}</Notice> : null}
          {profileFromPhone && !requestsSavedAt ? <Notice tone="neutral">{t('offline.savedProfile')}</Notice> : null}

          {activeTrip && <TripCard trip={activeTrip} onDirections={() => openDirections(activeTrip)} onDone={endTrip} />}

          {/* Readiness */}
          <View style={[s.card, { marginTop: 16 }]}>
            <View style={[s.row, { justifyContent: 'space-between' }]}>
              <Text style={s.overline}>{t('dash.readiness')}</Text>
              <StatusPill tone={eligible ? 'green' : 'amber'}>{eligible ? t('dash.eligible') : t('dash.recovering')}</StatusPill>
            </View>

            <View style={[s.row, { alignItems: 'flex-end', marginTop: 14, gap: 10 }]}>
              <Text style={[s.bigNum, { color: eligible ? color.greenText : color.text }]}>
                {eligible ? t('dash.readyBig') : daysRemaining}
              </Text>
              <Text style={s.bigNumSub}>
                {eligible ? (lastDonatedDate ? t('dash.daysSince', { days: daysElapsed }) : t('dash.noDonation')) : (daysRemaining === 1 ? t('dash.daysUntilOne') : t('dash.daysUntil'))}
              </Text>
            </View>

            <View style={s.meterTrack}>
              <View style={[s.meterFill, { width: `${progressPercent}%`, backgroundColor: eligible ? color.green : color.amber }]} />
            </View>
            <View style={[s.row, { justifyContent: 'space-between', marginTop: 8 }]}>
              <Text style={s.meterLabel}>{lastDonatedDate ? t('dash.dayOf', { day: Math.min(daysElapsed, COOLDOWN_DAYS), total: COOLDOWN_DAYS }) : t('dash.window', { days: COOLDOWN_DAYS })}</Text>
              <Text style={s.meterLabel}>{!eligible ? t('dash.eligibleOn', { date: getNextEligibleDateText() }) : `${Math.round(progressPercent)}%`}</Text>
            </View>
          </View>

          {/* Impact */}
          <View style={[s.card, s.row, { marginTop: 16, paddingVertical: 18 }]}>
            <Stat value={donationLog.length} label={donationLog.length === 1 ? t('dash.donationOne') : t('dash.donations')} />
            <View style={s.vDivider} />
            <Stat value={t(`language.${language}`)} label={t('dash.callLanguage')} />
            <View style={s.vDivider} />
            <Stat value={bg(displayGroup) || '—'} label={t('dash.yourGroup')} tone="red" />
          </View>

          {/* Profile */}
          <View style={[s.card, { marginTop: 16 }]}>
            <View style={[s.row, { gap: 12 }]}>
              {profilePic ? (
                <Image source={{ uri: profilePic }} style={s.avatarSm} />
              ) : (
                <View style={[s.avatarSm, s.avatarSmEmpty]}><Text style={s.avatarSmInitial}>{firstName ? firstName[0].toUpperCase() : '?'}</Text></View>
              )}
              <View style={{ flex: 1 }}>
                <Text style={s.profileName} numberOfLines={1}>{name}</Text>
                <Text style={s.profilePhone}>+91 {phone}</Text>
              </View>
              <View style={s.groupBadge}><Text style={s.groupBadgeText}>{bg(displayGroup)}</Text></View>
            </View>

            <View style={s.metaList}>
              <MetaRow label={t('dash.location')} value={address || t('common.notSet')} />
              <MetaRow label={t('dash.callLanguage')} value={t(`language.${language}`)} />
              <MetaRow label={t('dash.radius')} value={t('dash.radiusValue')} />
              <MetaRow label={t('dash.calls')} value={t({ on: 'dash.callsOn', off: 'dash.callsOff', paused: 'dash.callsBreak' }[callsStatus({ optedOut: callsOptOut, pausedUntil: callsPausedUntil })])} />
              <MetaRow label={t('dash.alerts')} value={t(`alerts.${alertsState}`)} last />
            </View>

            {alertsState === 'off' || alertsState === 'blocked' ? (
              <SecondaryButton onPress={turnOnAlerts} busy={alertsBusy} style={{ marginTop: 14 }}>
                {alertsState === 'blocked' ? t('alerts.allowInSettings') : t('alerts.turnOn')}
              </SecondaryButton>
            ) : null}

            {!callsOptOut ? (() => {
              const pause = pauseState(callsPausedUntil);
              return pause.paused ? (
                <View style={s.availabilityBox}>
                  <Text style={s.availabilityTitle}>{t('availability.pausedUntil', { date: t.date(pause.until) })}</Text>
                  <Text style={s.hint}>{t('availability.pausedBody')}</Text>
                  <SecondaryButton onPress={() => pauseFor(0)} busy={callsBusy} style={{ marginTop: 10 }}>
                    {t('availability.resume')}
                  </SecondaryButton>
                </View>
              ) : (
                <View style={s.availabilityBox}>
                  <Text style={s.availabilityTitle}>{t('availability.title')}</Text>
                  <Text style={s.hint}>{t('availability.body')}</Text>
                  <View style={[s.row, { gap: 8, marginTop: 10 }]}>
                    {PAUSE_OPTIONS.map((days) => (
                      <TouchableOpacity key={days} onPress={() => pauseFor(days)} disabled={callsBusy}
                        style={[s.smallBtn, { flex: 1, alignItems: 'center', paddingVertical: 10 }, callsBusy && { opacity: 0.5 }]}
                        accessibilityRole="button">
                        <Text style={s.smallBtnText}>{t(`availability.option.${days}`)}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                </View>
              );
            })() : null}

            <SecondaryButton onPress={toggleCalls} busy={callsBusy} style={{ marginTop: 14 }}>
              {callsOptOut ? t('dash.resumeCalls') : t('dash.pauseCalls')}
            </SecondaryButton>

            <View style={[s.row, { gap: 10, marginTop: 14 }]}>
              <SecondaryButton onPress={() => setIsEditing(true)} style={{ flex: 1 }}>{t('dash.editProfile')}</SecondaryButton>
              <TouchableOpacity onPress={confirmClearProfile} style={s.dangerBtn} accessibilityRole="button">
                <Text style={s.dangerBtnText}>{t('common.delete')}</Text>
              </TouchableOpacity>
            </View>

            <View style={[s.row, { justifyContent: 'center', gap: 18, marginTop: 16 }]}>
              <TouchableOpacity onPress={() => Linking.openURL(LEGAL_LINKS.privacy).catch(() => {})} accessibilityRole="link">
                <Text style={s.legalLink}>{t('legal.privacy')}</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => Linking.openURL(LEGAL_LINKS.terms).catch(() => {})} accessibilityRole="link">
                <Text style={s.legalLink}>{t('legal.terms')}</Text>
              </TouchableOpacity>
            </View>

            <LanguageSwitch style={{ marginTop: 18 }} />
          </View>

          {/* History */}
          <View style={[s.card, { marginTop: 16, paddingHorizontal: 0, paddingBottom: 6 }]}>
            <Text style={[s.overline, { paddingHorizontal: 18, marginBottom: 6 }]}>{t('dash.history')}</Text>
            {donationLog.length === 0 ? (
              <Text style={s.emptyText}>{t('dash.historyEmpty')}</Text>
            ) : (
              donationLog.map((log, i) => {
                const formattedDate = t.date(log.date, { year: 'numeric', month: 'short', day: 'numeric' });
                return (
                  <View key={log.id} style={[s.logItem, i < donationLog.length - 1 && s.logItemBorder]}>
                    <View style={s.logDot} />
                    <View style={{ flex: 1 }}>
                      <Text style={s.logHospital} numberOfLines={1}>{log.hospital}</Text>
                      <Text style={s.logDate}>{formattedDate}</Text>
                    </View>
                    <StatusPill tone="green">{t('dash.donated')}</StatusPill>
                  </View>
                );
              })
            )}
          </View>
        </View>
      )}
    </ScrollView>
  );
}

// ─── PIECES ───

function RequestCard({
  req, busy, highlighted, checking, answers, onAnswer, recoveringDays, onStartCheck, onStopCheck, onAccept, onDecline,
}) {
  const { color, s } = useContext(ThemeContext);
  const { t } = useContext(I18nContext);
  const critical = req.urgency === 'critical';
  const ago = minutesAgo(req.created_at, t);
  return (
    <View style={[s.requestCard, shadow, highlighted && { borderColor: color.red, borderWidth: 2 }]}>
      <View style={s.requestBand}>
        <View style={s.liveDot} />
        <Text style={s.requestBandText}>{critical ? t('requests.critical') : t('requests.urgent')}{ago ? ` · ${ago}` : ''}</Text>
      </View>
      <View style={{ padding: 18 }}>
        <View style={[s.row, { alignItems: 'flex-start', gap: 14 }]}>
          <View style={s.requestGroup}>
            <Text style={s.requestGroupText}>{bg(req.blood_group)}</Text>
            <Text style={s.requestUnits}>{req.units === 1 ? t('requests.unitOne') : t('requests.units', { count: req.units })}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={s.requestHospital}>{req.hospital_name}</Text>
            {req.address ? <Text style={s.requestAddr} numberOfLines={2}>{req.address}</Text> : null}
          </View>
        </View>

        <View style={s.requestStats}>
          <View style={{ flex: 1 }}>
            <Text style={s.statLabel}>{t('requests.distance')}</Text>
            <Text style={s.statValue}>{req.distance_km != null ? t('requests.km', { value: Number(req.distance_km).toFixed(1) }) : '—'}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={s.statLabel}>{t('requests.travel')}</Text>
            <Text style={s.statValue}>{req.eta_minutes != null ? t('requests.minutes', { value: req.eta_minutes }) : '—'}</Text>
          </View>
        </View>

        {checking ? (
          <HealthCheck answers={answers} onAnswer={onAnswer} recoveringDays={recoveringDays} busy={busy}
            onConfirm={onAccept} onDecline={onDecline} onBack={onStopCheck} />
        ) : (
          <>
            <TouchableOpacity onPress={onStartCheck} disabled={busy} style={[s.acceptBtn, busy && { opacity: 0.7 }]} accessibilityRole="button">
              {busy ? <ActivityIndicator color="#FFFFFF" /> : <Text style={s.acceptBtnText}>{t('requests.canDonate')}</Text>}
            </TouchableOpacity>
            <TouchableOpacity onPress={onDecline} disabled={busy} style={s.declineBtn} accessibilityRole="button">
              <Text style={s.declineBtnText}>{t('requests.cantMakeIt')}</Text>
            </TouchableOpacity>
          </>
        )}
      </View>
    </View>
  );
}

// Questions the donor answers before saying yes. Any unsafe answer turns "yes" into
// "let the hospital know", so the hospital can call someone else straight away.
function HealthCheck({ answers, onAnswer, recoveringDays, busy, onConfirm, onDecline, onBack }) {
  const { color, s } = useContext(ThemeContext);
  const { t } = useContext(I18nContext);
  const back = (
    <TouchableOpacity onPress={onBack} disabled={busy} style={s.declineBtn} accessibilityRole="button">
      <Text style={s.declineBtnText}>{t('eligibility.back')}</Text>
    </TouchableOpacity>
  );
  const tellHospital = (
    <TouchableOpacity onPress={onDecline} disabled={busy} style={[s.btnSecondary, { marginTop: 12 }]} accessibilityRole="button">
      {busy ? <ActivityIndicator color={color.text2} /> : <Text style={s.btnSecondaryText}>{t('eligibility.tellHospital')}</Text>}
    </TouchableOpacity>
  );

  if (recoveringDays > 0) {
    return (
      <View>
        <Notice tone="amber">{recoveringDays === 1 ? t('eligibility.recoveringOne') : t('eligibility.recovering', { days: recoveringDays })}</Notice>
        {tellHospital}
        {back}
      </View>
    );
  }

  const result = evaluateAnswers(answers);
  const failed = result.failed.length > 0;
  return (
    <View>
      <Text style={s.checkTitle}>{t('eligibility.title')}</Text>
      <Text style={[s.hint, { marginTop: 4 }]}>{t('eligibility.intro')}</Text>
      {HEALTH_QUESTIONS.map((q, i) => (
        <View key={q.id} style={[s.checkRow, i === 0 && { borderTopWidth: 0 }]}>
          <Text style={s.checkQuestion}>{t(`eligibility.${q.id}.question`)}</Text>
          <View style={[s.segmented, { marginTop: 8 }]} accessibilityRole="radiogroup">
            {['yes', 'no'].map((value) => {
              const active = answers[q.id] === value;
              return (
                <TouchableOpacity key={value} onPress={() => onAnswer(q.id, value)} disabled={busy}
                  accessibilityRole="radio" accessibilityState={{ selected: active }}
                  accessibilityLabel={`${t(`eligibility.${q.id}.question`)} ${t(`eligibility.${value}`)}`}
                  style={[s.segment, active && s.segmentActive]}>
                  <Text style={[s.segmentText, active && s.segmentTextActive]}>{t(`eligibility.${value}`)}</Text>
                </TouchableOpacity>
              );
            })}
          </View>
        </View>
      ))}

      {failed ? (
        <Notice tone="red">
          {`${t('eligibility.notToday')}\n${result.failed.map((id) => `• ${t(`eligibility.${id}.reason`)}`).join('\n')}\n${t('eligibility.notTodayBody')}`}
        </Notice>
      ) : null}

      {failed ? tellHospital : (
        <TouchableOpacity onPress={onConfirm} disabled={busy || !result.complete}
          style={[s.acceptBtn, { marginTop: 14 }, (busy || !result.complete) && { opacity: 0.5 }]}
          accessibilityRole="button" accessibilityState={{ disabled: busy || !result.complete }}>
          {busy ? <ActivityIndicator color="#FFFFFF" /> : <Text style={s.acceptBtnText}>{t('eligibility.confirm')}</Text>}
        </TouchableOpacity>
      )}
      {!failed && !result.complete ? <Text style={[s.hint, { textAlign: 'center' }]}>{t('eligibility.answerAll')}</Text> : null}
      <Text style={[s.hint, { textAlign: 'center', marginTop: 10 }]}>{t('eligibility.disclaimer')}</Text>
      {back}
    </View>
  );
}

function TripCard({ trip, onDirections, onDone }) {
  const { color, s } = useContext(ThemeContext);
  const { t } = useContext(I18nContext);
  return (
    <View style={[s.tripCard, shadow]}>
      <View style={[s.row, { justifyContent: 'space-between' }]}>
        <Text style={[s.overline, { color: color.greenText }]}>{t('trip.confirmed')}</Text>
        <StatusPill tone="green">{t('trip.enRoute')}</StatusPill>
      </View>
      <Text style={s.tripHospital}>{trip.hospital_name}</Text>
      {trip.address ? <Text style={s.requestAddr}>{trip.address}</Text> : null}
      <Text style={s.tripNote}>
        {trip.eta_minutes != null ? t('trip.noteEta', { minutes: trip.eta_minutes }) : t('trip.note')}
      </Text>
      <TouchableOpacity onPress={onDirections} style={s.tripBtn} accessibilityRole="button">
        <Text style={s.tripBtnText}>{t('trip.directions')}</Text>
      </TouchableOpacity>
      <TouchableOpacity onPress={onDone} style={{ alignSelf: 'center', marginTop: 12 }} accessibilityRole="button">
        <Text style={s.tripDismiss}>{t('trip.hide')}</Text>
      </TouchableOpacity>
    </View>
  );
}

function DropMark({ size = 24 }) {
  const { color } = useContext(ThemeContext);
  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center', marginRight: 9 }}>
      <View style={{
        width: size * 0.72, height: size * 0.72, backgroundColor: color.red,
        borderRadius: size * 0.36, borderTopLeftRadius: 0, transform: [{ rotate: '45deg' }], marginTop: size * 0.18,
      }} />
    </View>
  );
}

function ThemeSwitch({ theme, onPress }) {
  const { s } = useContext(ThemeContext);
  const { t } = useContext(I18nContext);
  return (
    <TouchableOpacity onPress={onPress} style={s.themeButton} accessibilityRole="button"
      accessibilityLabel={theme === 'dark' ? t('theme.switchToLight') : t('theme.switchToDark')}>
      <Text style={s.themeButtonText}>{theme === 'dark' ? t('theme.toLight') : t('theme.toDark')}</Text>
    </TouchableOpacity>
  );
}

// English, हिन्दी, தமிழ், each written in its own script so a donor can find theirs.
function LanguageSwitch({ style }) {
  const { s } = useContext(ThemeContext);
  const { t, language, setLanguage } = useContext(I18nContext);
  return (
    <View style={style}>
      <Text style={s.label}>{t('language.label')}</Text>
      <View style={s.segmented} accessibilityRole="radiogroup" accessibilityLabel={t('language.label')}>
        {APP_LANGUAGES.map((option) => {
          const active = language === option.code;
          return (
            <TouchableOpacity key={option.code} onPress={() => setLanguage(option.code)}
              accessibilityRole="radio" accessibilityState={{ selected: active }} accessibilityLabel={option.label}
              style={[s.segment, active && s.segmentActive]}>
              <Text style={[s.segmentText, active && s.segmentTextActive]}>{option.label}</Text>
            </TouchableOpacity>
          );
        })}
      </View>
    </View>
  );
}

function Field({ label, hint, children }) {
  const { s } = useContext(ThemeContext);
  return (
    <View style={{ marginBottom: 16 }}>
      <Text style={s.label}>{label}</Text>
      {children}
      {hint ? <Text style={s.hint}>{hint}</Text> : null}
    </View>
  );
}

function Notice({ tone, children }) {
  const { color, s } = useContext(ThemeContext);
  const map = {
    red: [color.redSurface, color.redBorder, color.redText],
    amber: [color.amberSurface, color.amberBorder, color.amberText],
    neutral: [color.surface2, color.border, color.text2],
  }[tone] || [color.surface2, color.border, color.text2];
  return (
    <View style={[s.notice, { backgroundColor: map[0], borderColor: map[1] }]}>
      <Text style={[s.noticeText, { color: map[2] }]}>{children}</Text>
    </View>
  );
}

function PrimaryButton({ onPress, busy, children, style }) {
  const { s } = useContext(ThemeContext);
  return (
    <TouchableOpacity onPress={onPress} disabled={busy} style={[s.btnPrimary, busy && { opacity: 0.75 }, style]} accessibilityRole="button">
      {busy ? <ActivityIndicator color="#FFFFFF" /> : <Text style={s.btnPrimaryText}>{children}</Text>}
    </TouchableOpacity>
  );
}

function SecondaryButton({ onPress, children, style, busy = false }) {
  const { s } = useContext(ThemeContext);
  return (
    <TouchableOpacity onPress={onPress} disabled={busy} style={[s.btnSecondary, busy && { opacity: 0.6 }, style]} accessibilityRole="button">
      <Text style={s.btnSecondaryText}>{children}</Text>
    </TouchableOpacity>
  );
}

function StatusPill({ tone, children }) {
  const { color, s } = useContext(ThemeContext);
  const map = {
    green: [color.greenSurface, color.greenText],
    amber: [color.amberSurface, color.amberText],
    red: [color.redSurface, color.redText],
  }[tone];
  return (
    <View style={[s.pill, { backgroundColor: map[0] }]}>
      <Text style={[s.pillText, { color: map[1] }]}>{children}</Text>
    </View>
  );
}

function Stat({ value, label, tone }) {
  const { color, s } = useContext(ThemeContext);
  return (
    <View style={{ flex: 1, alignItems: 'center' }}>
      <Text style={[s.statBig, tone === 'red' && { color: color.redText }]} numberOfLines={1}>{value}</Text>
      <Text style={s.statLabel}>{label}</Text>
    </View>
  );
}

function MetaRow({ label, value, last }) {
  const { color, s } = useContext(ThemeContext);
  return (
    <View style={[s.metaRow, !last && { borderBottomWidth: 1, borderBottomColor: color.divider }]}>
      <Text style={s.metaLabel}>{label}</Text>
      <Text style={s.metaValue} numberOfLines={1}>{value}</Text>
    </View>
  );
}

function Fact({ title, body, last }) {
  const { color, s } = useContext(ThemeContext);
  return (
    <View style={[s.fact, !last && { borderBottomWidth: 1, borderBottomColor: color.divider }]}>
      <Text style={s.factTitle}>{title}</Text>
      <Text style={s.factBody}>{body}</Text>
    </View>
  );
}

const createStyles = (color) => StyleSheet.create({
  root: { flex: 1, backgroundColor: color.canvas },
  rootContent: { paddingHorizontal: 16, paddingTop: 56, paddingBottom: 96 },
  authContent: { flexGrow: 1, paddingHorizontal: 24, paddingTop: 58, paddingBottom: 48, backgroundColor: color.canvas },
  row: { flexDirection: 'row', alignItems: 'center' },

  brand: { fontSize: 19, fontWeight: '700', color: color.text, letterSpacing: -0.4 },
  themeButton: { backgroundColor: color.surface2, borderWidth: 1, borderColor: color.border, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 8 },
  themeButtonText: { color: color.text2, fontSize: 12, fontWeight: '700' },
  authHero: { backgroundColor: color.surface2, borderRadius: 20, borderWidth: 1, borderColor: color.border, padding: 22, marginBottom: 32 },
  authHeroEyebrow: { color: color.redText, fontSize: 10, fontWeight: '800', letterSpacing: 1.5 },
  authHeroTitle: { color: color.text, fontSize: 26, fontWeight: '800', lineHeight: 31, letterSpacing: -0.7, marginTop: 12 },
  authHeroBody: { color: color.text2, fontSize: 13.5, lineHeight: 20, marginTop: 10 },
  heroSteps: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 22, borderTopWidth: 1, borderTopColor: color.border, paddingTop: 14 },
  heroStep: { color: color.blueText, fontSize: 11.5, fontWeight: '700' },
  welcomeBanner: { backgroundColor: color.blueSurface, borderWidth: 1, borderColor: color.border, borderRadius: 18, padding: 20, marginBottom: 22 },
  welcomeEyebrow: { color: color.blueText, fontSize: 10.5, fontWeight: '800', letterSpacing: 1.1 },
  welcomeTitle: { color: color.text, fontSize: 24, fontWeight: '800', letterSpacing: -0.5, marginTop: 8 },
  welcomeBody: { color: color.text2, fontSize: 13, lineHeight: 19, marginTop: 7 },
  h1: { fontSize: 27, fontWeight: '700', color: color.text, letterSpacing: -0.6 },
  lede: { fontSize: 14.5, color: color.text2, lineHeight: 22, marginTop: 8, marginBottom: 28 },
  switchText: { fontSize: 14, color: color.text2 },
  switchLink: { color: color.blue, fontWeight: '600' },
  authFacts: { marginTop: 40, borderWidth: 1, borderColor: color.border, borderRadius: radius.card, backgroundColor: color.surface2 },
  fact: { paddingHorizontal: 16, paddingVertical: 14 },
  factTitle: { fontSize: 13.5, fontWeight: '600', color: color.text },
  factBody: { fontSize: 12.5, color: color.text2, marginTop: 3, lineHeight: 18 },

  card: { backgroundColor: color.surface, borderWidth: 1, borderColor: color.border, borderRadius: radius.card, padding: 18 },
  cardTitle: { color: color.text, fontWeight: '700', fontSize: 20, letterSpacing: -0.3, marginTop: 8 },
  cardDesc: { color: color.text2, fontSize: 13, lineHeight: 19, marginTop: 6, marginBottom: 20 },
  overline: { fontSize: 11, fontWeight: '700', color: color.muted, letterSpacing: 0.8, textTransform: 'uppercase' },

  label: { color: color.text, fontSize: 13, fontWeight: '600', marginBottom: 8 },
  hint: { color: color.muted, fontSize: 12, marginTop: 6 },
  input: { backgroundColor: color.surface, borderWidth: 1, borderColor: color.border, borderRadius: radius.input, paddingHorizontal: 14, paddingVertical: 12, color: color.text, fontSize: 15 },
  inputBare: { flex: 1, paddingHorizontal: 12, paddingVertical: 12, color: color.text, fontSize: 15 },
  phoneRow: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderColor: color.border, borderRadius: radius.input, backgroundColor: color.surface, overflow: 'hidden' },
  phonePrefix: { paddingHorizontal: 12, paddingVertical: 12, backgroundColor: color.surface2, color: color.text2, fontWeight: '600', fontSize: 15, borderRightWidth: 1, borderRightColor: color.border, fontFamily: mono },

  notice: { borderWidth: 1, borderRadius: radius.input, padding: 12, marginTop: 12 },
  noticeText: { fontSize: 13, lineHeight: 19, fontWeight: '500' },

  btnPrimary: { backgroundColor: color.blue, paddingVertical: 16, borderRadius: radius.input, alignItems: 'center', justifyContent: 'center' },
  btnPrimaryText: { color: '#FFFFFF', fontSize: 15, fontWeight: '600' },
  btnSecondary: { backgroundColor: color.surface, borderWidth: 1, borderColor: color.border, borderRadius: radius.input, paddingVertical: 12, alignItems: 'center' },
  btnSecondaryText: { color: color.text, fontSize: 14, fontWeight: '600' },
  dangerBtn: { borderWidth: 1, borderColor: color.redBorder, borderRadius: radius.input, paddingHorizontal: 18, paddingVertical: 12, alignItems: 'center' },
  dangerBtnText: { color: color.redText, fontSize: 14, fontWeight: '600' },
  smallBtn: { borderWidth: 1, borderColor: color.border, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 7, backgroundColor: color.surface },
  smallBtnText: { color: color.text2, fontSize: 12.5, fontWeight: '600' },

  avatarLg: { width: 84, height: 84, borderRadius: 42, backgroundColor: color.surface2, borderWidth: 1, borderColor: color.border, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  avatarLgImage: { width: '100%', height: '100%' },
  avatarLgInitial: { fontSize: 28, fontWeight: '600', color: color.text2 },
  avatarHint: { fontSize: 12.5, color: color.blue, fontWeight: '600', marginTop: 8 },

  chipGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, justifyContent: 'space-between' },
  groupChip: { width: '23%', alignItems: 'center', paddingVertical: 12, borderRadius: radius.input, borderWidth: 1, borderColor: color.border, backgroundColor: color.surface },
  groupChipActive: { borderColor: color.red, borderWidth: 1.5, backgroundColor: color.redSurface },
  groupChipText: { fontSize: 15, fontWeight: '600', color: color.text2 },
  groupChipTextActive: { color: color.redText, fontWeight: '700' },

  segmented: { flexDirection: 'row', backgroundColor: color.track, borderRadius: radius.input, padding: 3 },
  segment: { flex: 1, alignItems: 'center', paddingVertical: 10, borderRadius: 7 },
  segmentActive: { backgroundColor: color.surface, ...shadow },
  segmentText: { fontSize: 13.5, color: color.text2, fontWeight: '500' },
  segmentTextActive: { color: color.text, fontWeight: '600' },

  gpsBtn: { backgroundColor: color.greenSurface, borderWidth: 1, borderColor: color.greenBorder, borderRadius: radius.input, paddingVertical: 14, paddingHorizontal: 16 },
  gpsDot: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: color.green, alignItems: 'center', justifyContent: 'center' },
  gpsDotInner: { width: 8, height: 8, borderRadius: 4, backgroundColor: color.green },
  gpsBtnText: { color: color.greenText, fontSize: 14.5, fontWeight: '600' },
  gpsBtnSub: { color: color.greenText, opacity: 0.75, fontSize: 12, marginTop: 2 },
  orRow: { flexDirection: 'row', alignItems: 'center', marginVertical: 14 },
  orLine: { flex: 1, height: 1, backgroundColor: color.border },
  orText: { color: color.muted, fontSize: 12, marginHorizontal: 10 },
  locationConfirmed: { backgroundColor: color.surface2, borderWidth: 1, borderColor: color.border, borderRadius: radius.input, padding: 12 },
  locationTag: { fontSize: 11.5, fontWeight: '600', color: color.greenText },
  locationAddr: { fontSize: 13.5, color: color.text, marginTop: 2 },
  locationPreview: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12, marginTop: 10, backgroundColor: color.blueSurface, borderRadius: 10 },
  locationPreviewPin: { color: color.blueText, fontSize: 24, fontWeight: '700' },
  locationPreviewTitle: { color: color.text, fontSize: 13, fontWeight: '700' },
  locationPreviewCoords: { color: color.text2, fontSize: 11.5, marginTop: 3 },

  greeting: { fontSize: 25, fontWeight: '700', color: color.text, letterSpacing: -0.5 },
  greetingSub: { fontSize: 14, color: color.text2, marginTop: 4, marginBottom: 16, lineHeight: 20 },

  requestCard: { backgroundColor: color.surface, borderWidth: 1, borderColor: color.redBorder, borderRadius: radius.card, overflow: 'hidden', marginBottom: 12 },
  requestBand: { flexDirection: 'row', alignItems: 'center', backgroundColor: color.redSurface, paddingHorizontal: 18, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: color.redBorder },
  liveDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: color.red, marginRight: 8 },
  requestBandText: { fontSize: 12.5, fontWeight: '700', color: color.redText },
  requestGroup: { width: 70, paddingVertical: 10, borderRadius: 10, backgroundColor: color.redSurface, alignItems: 'center' },
  requestGroupText: { fontSize: 26, fontWeight: '800', color: color.redText, letterSpacing: -0.5 },
  requestUnits: { fontSize: 11.5, color: color.redText, fontWeight: '600', marginTop: 1 },
  requestHospital: { fontSize: 17, fontWeight: '700', color: color.text, letterSpacing: -0.2 },
  requestAddr: { fontSize: 13, color: color.text2, marginTop: 4, lineHeight: 19 },
  requestStats: { flexDirection: 'row', marginTop: 16, marginBottom: 16, paddingTop: 14, borderTopWidth: 1, borderTopColor: color.divider },
  statLabel: { fontSize: 11.5, color: color.muted, fontWeight: '600', marginTop: 2 },
  statValue: { fontSize: 17, fontWeight: '700', color: color.text, marginTop: 3, fontFamily: mono },
  acceptBtn: { backgroundColor: color.red, borderRadius: radius.input, paddingVertical: 15, alignItems: 'center' },
  acceptBtnText: { color: '#FFFFFF', fontSize: 15.5, fontWeight: '700' },
  declineBtn: { alignItems: 'center', paddingVertical: 12, marginTop: 4 },
  declineBtnText: { color: color.text2, fontSize: 14, fontWeight: '600' },

  availabilityBox: { marginTop: 14, padding: 12, borderRadius: radius.input, backgroundColor: color.surface2, borderWidth: 1, borderColor: color.border },
  availabilityTitle: { fontSize: 14, fontWeight: '700', color: color.text },
  legalLink: { fontSize: 12.5, color: color.blue, fontWeight: '600', textDecorationLine: 'underline' },
  checkTitle: { fontSize: 16, fontWeight: '700', color: color.text },
  checkRow: { paddingVertical: 12, borderTopWidth: 1, borderTopColor: color.divider },
  checkQuestion: { fontSize: 14, color: color.text, lineHeight: 20 },

  tripCard: { backgroundColor: color.surface, borderWidth: 1, borderColor: color.greenBorder, borderRadius: radius.card, padding: 18, marginBottom: 4 },
  tripHospital: { fontSize: 18, fontWeight: '700', color: color.text, marginTop: 12 },
  tripNote: { fontSize: 13, color: color.text2, lineHeight: 19, marginTop: 12 },
  tripBtn: { backgroundColor: color.green, borderRadius: radius.input, paddingVertical: 14, alignItems: 'center', marginTop: 16 },
  tripBtnText: { color: '#FFFFFF', fontSize: 15, fontWeight: '700' },
  tripDismiss: { fontSize: 13, color: color.muted, fontWeight: '600' },

  pill: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  pillText: { fontSize: 12, fontWeight: '700' },
  bigNum: { fontSize: 40, fontWeight: '700', letterSpacing: -1, lineHeight: 44 },
  bigNumSub: { flex: 1, fontSize: 13, color: color.text2, marginBottom: 6, lineHeight: 18 },
  meterTrack: { height: 8, borderRadius: 999, backgroundColor: color.track, overflow: 'hidden', marginTop: 16 },
  meterFill: { height: '100%', borderRadius: 999 },
  meterLabel: { fontSize: 12, color: color.muted },

  statBig: { fontSize: 20, fontWeight: '700', color: color.text, letterSpacing: -0.3 },
  vDivider: { width: 1, alignSelf: 'stretch', backgroundColor: color.divider },

  avatarSm: { width: 46, height: 46, borderRadius: 23 },
  avatarSmEmpty: { backgroundColor: color.surface2, borderWidth: 1, borderColor: color.border, alignItems: 'center', justifyContent: 'center' },
  avatarSmInitial: { fontSize: 17, fontWeight: '600', color: color.text2 },
  profileName: { fontSize: 16.5, fontWeight: '700', color: color.text },
  profilePhone: { fontSize: 13, color: color.text2, marginTop: 2, fontFamily: mono },
  groupBadge: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 10, backgroundColor: color.redSurface },
  groupBadgeText: { fontSize: 18, fontWeight: '800', color: color.redText },
  metaList: { marginTop: 14, borderTopWidth: 1, borderTopColor: color.divider },
  metaRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 11, gap: 16 },
  metaLabel: { fontSize: 13, color: color.text2 },
  metaValue: { flex: 1, textAlign: 'right', fontSize: 13, color: color.text, fontWeight: '500' },

  emptyText: { fontSize: 13, color: color.muted, paddingHorizontal: 18, paddingVertical: 14, lineHeight: 19 },
  logItem: { flexDirection: 'row', alignItems: 'center', paddingVertical: 13, paddingHorizontal: 18, gap: 12 },
  logItemBorder: { borderBottomWidth: 1, borderBottomColor: color.divider },
  logDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: color.green },
  logHospital: { fontSize: 14, fontWeight: '600', color: color.text },
  logDate: { fontSize: 12, color: color.muted, marginTop: 2 },
});
