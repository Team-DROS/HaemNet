import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import {
  View, Text, TextInput, TouchableOpacity, ScrollView, ActivityIndicator, StyleSheet,
  Linking, Image, Alert, RefreshControl, AppState,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Location from 'expo-location';
import MapView, { Marker } from 'react-native-maps';
import * as ImagePicker from 'expo-image-picker';
import { bg, color, mono, radius, shadow } from './theme';

const COOLDOWN_DAYS = 56;
const MS_IN_A_DAY = 24 * 60 * 60 * 1000;
const DEFAULT_LAT = 12.9716;
const DEFAULT_LNG = 77.5946;
const POLL_MS = 15000;

const BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-', 'Others'];
// The AI voice agent speaks these three languages. Anything else falls back to English on the server.
const LANGUAGES = ['English', 'Hindi', 'Tamil'];

// Configure EXPO_PUBLIC_API_URL per environment (EAS/local .env).
const SERVER_BASE_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';

const withCountryCode = (p) => (p.startsWith('+91') ? p : `+91${p}`);
const localDigits = (p) => (p || '').replace(/^\+91/, '').replace(/[^0-9]/g, '').slice(-10);

// Server timestamps are UTC; older rows may lack the zone suffix.
function parseUtc(value) {
  if (!value) return NaN;
  const str = String(value);
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(str) ? str : `${str}Z`).getTime();
}

function minutesAgo(value) {
  const t = parseUtc(value);
  if (Number.isNaN(t)) return null;
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  return `${Math.floor(mins / 60)} h ago`;
}

function openDirections(target) {
  const dest = target.lat && target.lng ? `${target.lat},${target.lng}` : encodeURIComponent(target.address || target.hospital_name || '');
  Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${dest}`);
}

export default function DonorApp() {
  // ─── AUTHENTICATION STATE ───
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [currentUser, setCurrentUser] = useState(null); // { id: 10-digit phone, token }
  const [authStep, setAuthStep] = useState('phone'); // 'phone' | 'code'
  const [loginId, setLoginId] = useState('');
  const [code, setCode] = useState('');
  const [devCode, setDevCode] = useState(null); // only returned by a development server
  const [resendAt, setResendAt] = useState(0);
  const [authError, setAuthError] = useState('');
  const [authNotice, setAuthNotice] = useState('');
  const [authLoading, setAuthLoading] = useState(false);
  const [clock, setClock] = useState(Date.now());

  // ─── PROFILE STATE ───
  const [name, setName] = useState('');
  const [phone, setPhone] = useState(''); // 10 local digits, no country code
  const [bloodGroup, setBloodGroup] = useState('O+');
  const [customBloodGroup, setCustomBloodGroup] = useState('');
  const [language, setLanguage] = useState('English');
  const [lat, setLat] = useState(DEFAULT_LAT);
  const [lng, setLng] = useState(DEFAULT_LNG);
  const [address, setAddress] = useState('');
  const [locationSource, setLocationSource] = useState(null); // 'gps' | 'manual' | null
  const [profilePic, setProfilePic] = useState(null);

  const [isRegistered, setIsRegistered] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [regError, setRegError] = useState('');

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
  const [responding, setResponding] = useState(null); // dispatch_id being answered
  const [respondMsg, setRespondMsg] = useState('');
  const [activeTrip, setActiveTrip] = useState(null); // accepted request the donor is travelling to

  useEffect(() => { checkLoginStatus(); }, []);
  useEffect(() => {
    if (authStep !== 'code') return undefined;
    const t = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(t);
  }, [authStep]);
  useEffect(() => { if (isLoggedIn && currentUser) loadProfile(); }, [isLoggedIn, currentUser]);
  useEffect(() => { calculateCooldown(); }, [lastDonatedDate]);

  // ─── AUTHENTICATION ───
  // Donors sign in with their phone number and a 6-digit SMS code. The server
  // returns a donor token that every donor endpoint requires.
  const SESSION_KEY = '@donor_session';
  const userRef = useRef(null);
  userRef.current = currentUser;

  const api = async (method, path, data) => {
    const token = userRef.current?.token;
    try {
      return await axios({
        method, url: `${SERVER_BASE_URL}${path}`, data,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        timeout: 15000,
      });
    } catch (err) {
      if (err.response?.status === 401 && token) {
        await handleLogout('Your session expired. Sign in again with your phone number.');
      }
      throw err;
    }
  };

  const checkLoginStatus = async () => {
    try {
      await AsyncStorage.removeItem('@current_user'); // pre-OTP builds kept an unverified session here
      const saved = await AsyncStorage.getItem(SESSION_KEY);
      if (saved) {
        const session = JSON.parse(saved);
        if (session?.token && session?.id) {
          setCurrentUser(session);
          setIsLoggedIn(true);
        }
      }
    } catch (e) {
      Alert.alert('Sign in', 'Could not check your sign-in status.');
    }
  };

  const serverError = (err, fallback) => err.response?.data?.detail || (err.response ? fallback : 'Cannot reach HaemNet. Check your connection.');

  const requestCode = async () => {
    setAuthError(''); setAuthNotice('');
    if (loginId.length !== 10) return setAuthError('Enter your 10-digit mobile number.');
    setAuthLoading(true);
    try {
      const res = await axios.post(`${SERVER_BASE_URL}/api/donor/auth/request`, { phone: loginId }, { timeout: 15000 });
      setDevCode(res.data.dev_code || null);
      setCode('');
      setAuthStep('code');
      setResendAt(Date.now() + 30000);
      setClock(Date.now());
      setAuthNotice(`We sent a 6-digit code to +91 ${loginId}.`);
    } catch (err) {
      setAuthError(serverError(err, 'Could not send the code.'));
    }
    setAuthLoading(false);
  };

  const verifyCode = async () => {
    setAuthError('');
    if (!/^\d{6}$/.test(code)) return setAuthError('Enter the 6-digit code from the SMS.');
    setAuthLoading(true);
    try {
      const res = await axios.post(`${SERVER_BASE_URL}/api/donor/auth/verify`, { phone: loginId, code }, { timeout: 15000 });
      const session = { id: localDigits(res.data.phone), token: res.data.access_token };
      await AsyncStorage.setItem(SESSION_KEY, JSON.stringify(session));
      setAuthStep('phone'); setCode(''); setDevCode(null); setAuthNotice('');
      setCurrentUser(session);
      setIsLoggedIn(true);
    } catch (err) {
      setAuthError(serverError(err, 'That code did not work.'));
    }
    setAuthLoading(false);
  };

  const handleLogout = async (message) => {
    await AsyncStorage.removeItem(SESSION_KEY);
    setIsLoggedIn(false);
    setCurrentUser(null);
    setLoginId('');
    setCode('');
    setAuthStep('phone');
    setIsRegistered(false);
    setRequests([]);
    setActiveTrip(null);
    setAuthNotice(typeof message === 'string' ? message : '');
  };

  // ─── PROFILE LOGIC ───
  const getProfileKey = () => `@donor_profile_${currentUser.id}`;
  const getLogKey = () => `@donor_log_${currentUser.id}`;
  const getTripKey = () => `@donor_trip_${currentUser.id}`;

  const loadProfile = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const savedProfile = await AsyncStorage.getItem(getProfileKey());
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
        setLat(parseFloat(profile.lat) || DEFAULT_LAT);
        setLng(parseFloat(profile.lng) || DEFAULT_LNG);
        setAddress(profile.address || '');
        setLocationSource(profile.location_source || null);
        setProfilePic(profile.profilePic || null);
        if (profile.last_donated_date) {
          setLastDonatedDate(new Date(profile.last_donated_date));
        }
        setIsRegistered(true);
      } else {
        // Reset state for new user; the login number doubles as the donor phone.
        setName(''); setPhone(localDigits(currentUser.id)); setBloodGroup('O+'); setCustomBloodGroup(''); setLanguage('English');
        setLat(DEFAULT_LAT); setLng(DEFAULT_LNG); setAddress(''); setLocationSource(null);
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
        if (!savedProfile && backendProfile) {
          setName(backendProfile.name || '');
          const serverGroup = backendProfile.blood_group || 'O+';
          if (BLOOD_GROUPS.includes(serverGroup)) setBloodGroup(serverGroup);
          else { setBloodGroup('Others'); setCustomBloodGroup(serverGroup); }
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
      } catch (backendErr) {
        console.log('Could not sync with backend:', backendErr.message);
      }

      setDonationLog(currentLog);
    } catch (err) {
      Alert.alert('Error', 'Failed to load profile');
    }
    if (isRefresh) {
      await fetchRequests();
      setRefreshing(false);
    }
  };

  const handleRegister = async () => {
    setRegError('');
    if (!name.trim()) return setRegError('Name is required.');
    if (!phone.trim()) return setRegError('Phone number is required.');
    if (phone.length !== 10) return setRegError('Phone number must be exactly 10 digits.');
    if (!locationSource) return setRegError('Set your location with GPS or type your area.');

    const finalBloodGroup = bloodGroup === 'Others' ? customBloodGroup.trim() : bloodGroup;
    if (!finalBloodGroup) return setRegError('Specify your blood group.');

    const finalPhone = withCountryCode(currentUser.id); // always the SMS-verified number

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
      });
      await AsyncStorage.setItem(getProfileKey(), JSON.stringify(profile));
      setIsSaving(false); setIsRegistered(true); setIsEditing(false);
    } catch (err) {
      setIsSaving(false);
      const errorMsg = err.response ? `server returned ${err.response.status}` : err.message;
      setRegError(`Could not save your profile: ${errorMsg}`);
    }
  };

  const clearProfile = async () => {
    try {
      await api('delete', `/api/donor/profile/${encodeURIComponent(withCountryCode(currentUser.id))}`);

      await AsyncStorage.multiRemove([getProfileKey(), getLogKey(), getTripKey()]);
      setName(''); setPhone(localDigits(currentUser.id)); setBloodGroup('O+'); setCustomBloodGroup(''); setLanguage('English');
      setLat(DEFAULT_LAT); setLng(DEFAULT_LNG); setAddress(''); setLocationSource(null);
      setProfilePic(null); setLastDonatedDate(null); setDonationLog([]); setActiveTrip(null); setRequests([]);
      setIsRegistered(false); setIsEditing(false);
      Alert.alert('Profile deleted', 'You have been removed from the donor network.');
    } catch (err) {
      console.error(err);
      Alert.alert('Error', 'Failed to delete profile');
    }
  };

  const confirmClearProfile = () => {
    Alert.alert(
      'Delete your donor profile?',
      'Hospitals will no longer be able to reach you in an emergency.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: clearProfile },
      ],
    );
  };

  const handleNameChange = (text) => {
    if (/^[a-zA-Z\s]*$/.test(text)) setName(text);
  };

  const handleLoginIdChange = (text) => {
    setLoginId(text.replace(/[^0-9]/g, '').slice(0, 10));
  };

  // ─── LIVE REQUESTS ───
  const donorPhone = isRegistered && phone ? withCountryCode(phone) : null;

  const fetchRequests = useCallback(async () => {
    if (!donorPhone) return;
    try {
      const res = await api('get', `/api/donor/requests/${encodeURIComponent(donorPhone)}`);
      setRequests(res.data.requests || []);
      setRequestsError('');
    } catch (err) {
      if (err.response?.status !== 401) setRequestsError('Cannot reach HaemNet right now. Pull down to retry.');
    }
  }, [donorPhone]);

  // Poll while the app is in the foreground and the donor is registered.
  const appState = useRef(AppState.currentState);
  useEffect(() => {
    if (!donorPhone || isEditing) return undefined;
    fetchRequests();
    const timer = setInterval(() => { if (appState.current === 'active') fetchRequests(); }, POLL_MS);
    const sub = AppState.addEventListener('change', (next) => {
      if (appState.current !== 'active' && next === 'active') fetchRequests();
      appState.current = next;
    });
    return () => { clearInterval(timer); sub.remove(); };
  }, [donorPhone, isEditing, fetchRequests]);

  const respond = async (req, accept) => {
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
        setRespondMsg('Thanks for letting them know. The hospital will reach other donors.');
      }
    } catch (err) {
      const status = err.response?.status;
      if (status === 404 || status === 409) {
        setRequests((list) => list.filter((r) => r.dispatch_id !== req.dispatch_id));
        setRespondMsg(status === 404 ? 'That request has already been filled or closed.' : 'You already responded to this request.');
      } else {
        setRespondMsg('Could not send your answer. Check your connection and try again.');
      }
    }
    setResponding(null);
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
        const { status } = await ImagePicker.requestCameraPermissionsAsync();
        if (status !== 'granted') {
          Alert.alert('Permission needed', 'Camera permission is required to take a photo.');
          return;
        }
        result = await ImagePicker.launchCameraAsync({
          mediaTypes: ImagePicker.MediaTypeOptions.Images, allowsEditing: true, aspect: [1, 1], quality: 0.5,
        });
      } else {
        const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (status !== 'granted') {
          Alert.alert('Permission needed', 'Gallery permission is required to pick a photo.');
          return;
        }
        result = await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ImagePicker.MediaTypeOptions.Images, allowsEditing: true, aspect: [1, 1], quality: 0.5,
        });
      }
      if (!result.canceled && result.assets && result.assets.length > 0) {
        setProfilePic(result.assets[0].uri);
      }
    } catch (error) {
      Alert.alert('Error', 'Failed to pick image');
    }
  };

  const promptImagePicker = () => {
    Alert.alert('Profile photo', 'Choose an option', [
      { text: 'Take photo', onPress: () => pickImage(true) },
      { text: 'Choose from gallery', onPress: () => pickImage(false) },
      { text: 'Cancel', style: 'cancel' },
    ]);
  };

  // ─── LOCATION HELPERS ───
  const requestLocation = async () => {
    setLocationLoading(true);
    setLocationError('');
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        setLocationError('Location permission denied. Type your area below instead.');
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
      setLocationError(`Could not get location: ${err.message}. Type your area instead.`);
    }
    setLocationLoading(false);
  };

  const clearLocation = () => {
    setLocationSource(null);
    setAddress('');
    setLocationError('');
    setLat(DEFAULT_LAT);
    setLng(DEFAULT_LNG);
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
    setProgressPercent(Math.min(100, (diffDays / COOLDOWN_DAYS) * 100));
  };

  const getNextEligibleDateText = () => {
    if (!lastDonatedDate) return '';
    const eligibleDate = new Date(lastDonatedDate.getTime());
    eligibleDate.setDate(eligibleDate.getDate() + COOLDOWN_DAYS);
    return eligibleDate.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
  };

  // ─── RENDERERS ───

  if (!isLoggedIn) {
    return (
      <ScrollView style={s.root} contentContainerStyle={s.authContent} keyboardShouldPersistTaps="handled">
        <View style={[s.row, { marginBottom: 44 }]}>
          <DropMark size={26} />
          <Text style={s.brand}>HaemNet</Text>
        </View>

        <Text style={s.h1}>{authStep === 'phone' ? 'Sign in or join' : 'Enter your code'}</Text>
        <Text style={s.lede}>
          {authStep === 'phone'
            ? 'Use the mobile number hospitals should call. We text you a code to confirm it is yours.'
            : `Sent to +91 ${loginId}. It expires in 5 minutes.`}
        </Text>

        {authNotice && authStep === 'phone' ? <Notice tone="amber">{authNotice}</Notice> : null}

        {authStep === 'phone' ? (
          <Field label="Mobile number">
            <View style={s.phoneRow}>
              <Text style={s.phonePrefix}>+91</Text>
              <TextInput value={loginId} onChangeText={handleLoginIdChange} placeholder="98765 43210"
                placeholderTextColor={color.faint} keyboardType="phone-pad" maxLength={10} onSubmitEditing={requestCode}
                style={[s.inputBare, { fontFamily: mono }]} accessibilityLabel="Mobile number" />
            </View>
          </Field>
        ) : (
          <Field label="6-digit code">
            <TextInput value={code} onChangeText={(v) => setCode(v.replace(/[^0-9]/g, '').slice(0, 6))}
              placeholder="000000" placeholderTextColor={color.faint} keyboardType="number-pad" maxLength={6}
              textContentType="oneTimeCode" autoComplete="sms-otp" autoFocus onSubmitEditing={verifyCode}
              style={[s.input, s.codeInput]} accessibilityLabel="6-digit code" />
          </Field>
        )}

        {devCode && authStep === 'code' ? (
          <Notice tone="neutral">Development server: SMS is not configured, so your code is {devCode}.</Notice>
        ) : null}
        {authError ? <Notice tone="red">{authError}</Notice> : null}

        <PrimaryButton onPress={authStep === 'phone' ? requestCode : verifyCode} busy={authLoading} style={{ marginTop: 8 }}>
          {authStep === 'phone' ? 'Send code' : 'Verify and continue'}
        </PrimaryButton>

        {authStep === 'code' && (
          <View style={[s.row, { justifyContent: 'space-between', marginTop: 18 }]}>
            <TouchableOpacity onPress={() => { setAuthStep('phone'); setAuthError(''); setDevCode(null); }} accessibilityRole="button">
              <Text style={s.switchLink}>Change number</Text>
            </TouchableOpacity>
            {clock < resendAt ? (
              <Text style={s.switchText}>Resend in {Math.ceil((resendAt - clock) / 1000)}s</Text>
            ) : (
              <TouchableOpacity onPress={requestCode} disabled={authLoading} accessibilityRole="button">
                <Text style={s.switchLink}>Resend code</Text>
              </TouchableOpacity>
            )}
          </View>
        )}

        <View style={s.authFacts}>
          <Fact title="Only when it matters" body="You are contacted only when your group is needed within 10 km." />
          <Fact title="Your health first" body="The 56-day recovery window is tracked for you. No calls while you recover." />
          <Fact title="In your language" body="The AI caller speaks English, Hindi or Tamil." last />
        </View>
      </ScrollView>
    );
  }

  const renderLocationPicker = () => (
    <View style={{ marginTop: 18 }}>
      <Text style={s.label}>Your location</Text>

      {locationSource ? (
        <View style={s.locationConfirmed}>
          <View style={[s.row, { justifyContent: 'space-between', gap: 10 }]}>
            <View style={{ flex: 1 }}>
              <Text style={s.locationTag}>{locationSource === 'gps' ? 'GPS location set' : 'Area set'}</Text>
              <Text style={s.locationAddr} numberOfLines={2}>{address || 'Location set'}</Text>
            </View>
            <TouchableOpacity onPress={clearLocation} style={s.smallBtn} accessibilityRole="button">
              <Text style={s.smallBtnText}>Change</Text>
            </TouchableOpacity>
          </View>

          {locationSource === 'gps' && (
            <MapView
              style={s.mapPreview}
              initialRegion={{ latitude: lat, longitude: lng, latitudeDelta: 0.006, longitudeDelta: 0.006 }}
              scrollEnabled={false} zoomEnabled={false} pitchEnabled={false} rotateEnabled={false}
            >
              <Marker coordinate={{ latitude: lat, longitude: lng }} title={address} />
            </MapView>
          )}
        </View>
      ) : (
        <View>
          <TouchableOpacity onPress={requestLocation} disabled={locationLoading} style={s.gpsBtn} activeOpacity={0.85} accessibilityRole="button">
            {locationLoading ? (
              <View style={s.row}>
                <ActivityIndicator size="small" color={color.greenText} />
                <Text style={[s.gpsBtnText, { marginLeft: 10 }]}>Detecting location…</Text>
              </View>
            ) : (
              <View style={s.row}>
                <View style={s.gpsDot}><View style={s.gpsDotInner} /></View>
                <View style={{ marginLeft: 12 }}>
                  <Text style={s.gpsBtnText}>Use my current location</Text>
                  <Text style={s.gpsBtnSub}>Most accurate for matching</Text>
                </View>
              </View>
            )}
          </TouchableOpacity>

          {locationError ? <Notice tone="amber">{locationError}</Notice> : null}

          <View style={s.orRow}>
            <View style={s.orLine} />
            <Text style={s.orText}>or type your area</Text>
            <View style={s.orLine} />
          </View>

          <TextInput
            value={address}
            onChangeText={setAddress}
            onEndEditing={() => setLocationSource(address.trim() ? 'manual' : null)}
            placeholder="Koramangala, Bengaluru 560034"
            placeholderTextColor={color.faint}
            style={[s.input, { minHeight: 64, textAlignVertical: 'top' }]}
            multiline
            numberOfLines={2}
          />
        </View>
      )}
    </View>
  );

  const eligible = daysRemaining === 0;
  const firstName = (name || '').trim().split(/\s+/)[0];
  const displayGroup = bloodGroup === 'Others' ? customBloodGroup : bloodGroup;

  return (
    <ScrollView
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
        <TouchableOpacity onPress={() => handleLogout()} style={s.smallBtn} accessibilityRole="button">
          <Text style={s.smallBtnText}>Sign out</Text>
        </TouchableOpacity>
      </View>

      {!isRegistered || isEditing ? (
        <View style={s.card}>
          <Text style={s.cardTitle}>{isEditing ? 'Edit your donor profile' : 'Join the donor network'}</Text>
          <Text style={s.cardDesc}>Hospitals near you see only your blood group and distance until you accept a request.</Text>

          <View style={{ alignItems: 'center', marginBottom: 22 }}>
            <TouchableOpacity onPress={promptImagePicker} style={s.avatarLg} accessibilityRole="button" accessibilityLabel="Add profile photo">
              {profilePic ? (
                <Image source={{ uri: profilePic }} style={s.avatarLgImage} />
              ) : (
                <Text style={s.avatarLgInitial}>{firstName ? firstName[0].toUpperCase() : '+'}</Text>
              )}
            </TouchableOpacity>
            <Text style={s.avatarHint}>{profilePic ? 'Change photo' : 'Add photo (optional)'}</Text>
          </View>

          <Field label="Full name">
            <TextInput value={name} onChangeText={handleNameChange} placeholder="Ramesh Patel" placeholderTextColor={color.faint} style={s.input} />
          </Field>

          <Field label="Phone number" hint="Verified by SMS. Hospitals' AI caller rings this number.">
            <View style={[s.phoneRow, { backgroundColor: color.surface2 }]}>
              <Text style={s.phonePrefix}>+91</Text>
              <TextInput value={phone} editable={false} style={[s.inputBare, { fontFamily: mono, color: color.text2 }]}
                accessibilityLabel="Verified phone number" />
            </View>
          </Field>

          <Text style={s.label}>Blood group</Text>
          <View style={s.chipGrid}>
            {BLOOD_GROUPS.map((g) => {
              const active = bloodGroup === g;
              return (
                <TouchableOpacity key={g} onPress={() => setBloodGroup(g)} accessibilityRole="button" accessibilityState={{ selected: active }}
                  style={[s.groupChip, g === 'Others' && { width: '48%' }, active && s.groupChipActive]}>
                  <Text style={[s.groupChipText, active && s.groupChipTextActive]}>{g === 'Others' ? 'Other / rare' : bg(g)}</Text>
                </TouchableOpacity>
              );
            })}
          </View>

          {bloodGroup === 'Others' && (
            <TextInput value={customBloodGroup} onChangeText={setCustomBloodGroup} placeholder="e.g. Bombay (hh)"
              placeholderTextColor={color.faint} style={[s.input, { marginTop: 10 }]} />
          )}

          <Text style={[s.label, { marginTop: 18 }]}>AI call language</Text>
          <View style={s.segmented}>
            {LANGUAGES.map((lang) => {
              const active = language === lang;
              return (
                <TouchableOpacity key={lang} onPress={() => setLanguage(lang)} accessibilityRole="button" accessibilityState={{ selected: active }}
                  style={[s.segment, active && s.segmentActive]}>
                  <Text style={[s.segmentText, active && s.segmentTextActive]}>{lang}</Text>
                </TouchableOpacity>
              );
            })}
          </View>

          {renderLocationPicker()}

          {regError ? <Notice tone="red">{regError}</Notice> : null}

          <View style={[s.row, { marginTop: 22, gap: 10 }]}>
            {isEditing && (
              <SecondaryButton onPress={() => { setIsEditing(false); setRegError(''); }} style={{ flex: 1 }}>Cancel</SecondaryButton>
            )}
            <PrimaryButton onPress={handleRegister} busy={isSaving} style={{ flex: 2 }}>
              {isEditing ? 'Save changes' : 'Join the network'}
            </PrimaryButton>
          </View>
        </View>
      ) : (
        <View>
          <Text style={s.greeting}>Hi {firstName || 'there'}</Text>
          <Text style={s.greetingSub}>
            {requests.length
              ? `${requests.length === 1 ? 'A hospital needs' : `${requests.length} hospitals need`} your help right now.`
              : activeTrip ? 'Thank you for saying yes.' : eligible ? 'You are ready to donate if a hospital nearby needs you.' : 'You are recovering. We will not call you until you are ready.'}
          </Text>

          {requests.map((req) => (
            <RequestCard key={req.dispatch_id} req={req} busy={responding === req.dispatch_id}
              onAccept={() => respond(req, true)} onDecline={() => respond(req, false)} />
          ))}

          {respondMsg ? <Notice tone="neutral">{respondMsg}</Notice> : null}
          {requestsError ? <Notice tone="amber">{requestsError}</Notice> : null}

          {activeTrip && <TripCard trip={activeTrip} onDirections={() => openDirections(activeTrip)} onDone={endTrip} />}

          {/* Readiness */}
          <View style={[s.card, { marginTop: 16 }]}>
            <View style={[s.row, { justifyContent: 'space-between' }]}>
              <Text style={s.overline}>Donation readiness</Text>
              <StatusPill tone={eligible ? 'green' : 'amber'}>{eligible ? 'Eligible' : 'Recovering'}</StatusPill>
            </View>

            <View style={[s.row, { alignItems: 'flex-end', marginTop: 14, gap: 10 }]}>
              <Text style={[s.bigNum, { color: eligible ? color.greenText : color.text }]}>
                {eligible ? 'Ready' : daysRemaining}
              </Text>
              <Text style={s.bigNumSub}>
                {eligible ? (lastDonatedDate ? `${daysElapsed} days since your last donation` : 'No recent donation on record') : `day${daysRemaining === 1 ? '' : 's'} until you can donate again`}
              </Text>
            </View>

            <View style={s.meterTrack}>
              <View style={[s.meterFill, { width: `${progressPercent}%`, backgroundColor: eligible ? color.green : color.amber }]} />
            </View>
            <View style={[s.row, { justifyContent: 'space-between', marginTop: 8 }]}>
              <Text style={s.meterLabel}>{lastDonatedDate ? `Day ${Math.min(daysElapsed, COOLDOWN_DAYS)} of ${COOLDOWN_DAYS}` : `${COOLDOWN_DAYS}-day recovery window`}</Text>
              <Text style={s.meterLabel}>{!eligible ? `Eligible ${getNextEligibleDateText()}` : `${Math.round(progressPercent)}%`}</Text>
            </View>
          </View>

          {/* Impact */}
          <View style={[s.card, s.row, { marginTop: 16, paddingVertical: 18 }]}>
            <Stat value={donationLog.length} label={donationLog.length === 1 ? 'Donation' : 'Donations'} />
            <View style={s.vDivider} />
            <Stat value={donationLog.length ? `up to ${donationLog.length * 3}` : '0'} label="Patients helped" />
            <View style={s.vDivider} />
            <Stat value={bg(displayGroup) || '—'} label="Your group" tone="red" />
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
              <MetaRow label="Location" value={address || 'Not set'} />
              <MetaRow label="Call language" value={language} />
              <MetaRow label="Matching radius" value="10 km" last />
            </View>

            <View style={[s.row, { gap: 10, marginTop: 14 }]}>
              <SecondaryButton onPress={() => setIsEditing(true)} style={{ flex: 1 }}>Edit profile</SecondaryButton>
              <TouchableOpacity onPress={confirmClearProfile} style={s.dangerBtn} accessibilityRole="button">
                <Text style={s.dangerBtnText}>Delete</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* History */}
          <View style={[s.card, { marginTop: 16, paddingHorizontal: 0, paddingBottom: 6 }]}>
            <Text style={[s.overline, { paddingHorizontal: 18, marginBottom: 6 }]}>Donation history</Text>
            {donationLog.length === 0 ? (
              <Text style={s.emptyText}>No donations recorded yet. When a hospital logs your donation it appears here.</Text>
            ) : (
              donationLog.map((log, i) => {
                const formattedDate = new Date(log.date).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
                return (
                  <View key={log.id} style={[s.logItem, i < donationLog.length - 1 && s.logItemBorder]}>
                    <View style={s.logDot} />
                    <View style={{ flex: 1 }}>
                      <Text style={s.logHospital} numberOfLines={1}>{log.hospital}</Text>
                      <Text style={s.logDate}>{formattedDate}</Text>
                    </View>
                    <StatusPill tone="green">Donated</StatusPill>
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

function RequestCard({ req, busy, onAccept, onDecline }) {
  const critical = req.urgency === 'critical';
  const ago = minutesAgo(req.created_at);
  return (
    <View style={[s.requestCard, shadow]}>
      <View style={s.requestBand}>
        <View style={s.liveDot} />
        <Text style={s.requestBandText}>{critical ? 'Critical request' : 'Urgent request'}{ago ? ` · ${ago}` : ''}</Text>
      </View>
      <View style={{ padding: 18 }}>
        <View style={[s.row, { alignItems: 'flex-start', gap: 14 }]}>
          <View style={s.requestGroup}>
            <Text style={s.requestGroupText}>{bg(req.blood_group)}</Text>
            <Text style={s.requestUnits}>{req.units} unit{req.units === 1 ? '' : 's'}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={s.requestHospital}>{req.hospital_name}</Text>
            {req.address ? <Text style={s.requestAddr} numberOfLines={2}>{req.address}</Text> : null}
          </View>
        </View>

        <View style={s.requestStats}>
          <View style={{ flex: 1 }}>
            <Text style={s.statLabel}>Distance</Text>
            <Text style={s.statValue}>{req.distance_km != null ? `${Number(req.distance_km).toFixed(1)} km` : '—'}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={s.statLabel}>Est. travel</Text>
            <Text style={s.statValue}>{req.eta_minutes != null ? `${req.eta_minutes} min` : '—'}</Text>
          </View>
        </View>

        <TouchableOpacity onPress={onAccept} disabled={busy} style={[s.acceptBtn, busy && { opacity: 0.7 }]} accessibilityRole="button">
          {busy ? <ActivityIndicator color="#FFFFFF" /> : <Text style={s.acceptBtnText}>I can donate</Text>}
        </TouchableOpacity>
        <TouchableOpacity onPress={onDecline} disabled={busy} style={s.declineBtn} accessibilityRole="button">
          <Text style={s.declineBtnText}>I can't make it</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

function TripCard({ trip, onDirections, onDone }) {
  return (
    <View style={[s.tripCard, shadow]}>
      <View style={[s.row, { justifyContent: 'space-between' }]}>
        <Text style={[s.overline, { color: color.greenText }]}>You're confirmed</Text>
        <StatusPill tone="green">En route</StatusPill>
      </View>
      <Text style={s.tripHospital}>{trip.hospital_name}</Text>
      {trip.address ? <Text style={s.requestAddr}>{trip.address}</Text> : null}
      <Text style={s.tripNote}>
        The blood bank can see you are on your way{trip.eta_minutes != null ? ` (about ${trip.eta_minutes} min)` : ''}. Bring a photo ID and eat something light before you donate.
      </Text>
      <TouchableOpacity onPress={onDirections} style={s.tripBtn} accessibilityRole="button">
        <Text style={s.tripBtnText}>Get directions</Text>
      </TouchableOpacity>
      <TouchableOpacity onPress={onDone} style={{ alignSelf: 'center', marginTop: 12 }} accessibilityRole="button">
        <Text style={s.tripDismiss}>Hide this card</Text>
      </TouchableOpacity>
    </View>
  );
}

function DropMark({ size = 24 }) {
  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center', marginRight: 9 }}>
      <View style={{
        width: size * 0.72, height: size * 0.72, backgroundColor: color.red,
        borderRadius: size * 0.36, borderTopLeftRadius: 0, transform: [{ rotate: '45deg' }], marginTop: size * 0.18,
      }} />
    </View>
  );
}

function Field({ label, hint, children }) {
  return (
    <View style={{ marginBottom: 16 }}>
      <Text style={s.label}>{label}</Text>
      {children}
      {hint ? <Text style={s.hint}>{hint}</Text> : null}
    </View>
  );
}

function Notice({ tone, children }) {
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
  return (
    <TouchableOpacity onPress={onPress} disabled={busy} style={[s.btnPrimary, busy && { opacity: 0.75 }, style]} accessibilityRole="button">
      {busy ? <ActivityIndicator color="#FFFFFF" /> : <Text style={s.btnPrimaryText}>{children}</Text>}
    </TouchableOpacity>
  );
}

function SecondaryButton({ onPress, children, style }) {
  return (
    <TouchableOpacity onPress={onPress} style={[s.btnSecondary, style]} accessibilityRole="button">
      <Text style={s.btnSecondaryText}>{children}</Text>
    </TouchableOpacity>
  );
}

function StatusPill({ tone, children }) {
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
  return (
    <View style={{ flex: 1, alignItems: 'center' }}>
      <Text style={[s.statBig, tone === 'red' && { color: color.redText }]} numberOfLines={1}>{value}</Text>
      <Text style={s.statLabel}>{label}</Text>
    </View>
  );
}

function MetaRow({ label, value, last }) {
  return (
    <View style={[s.metaRow, !last && { borderBottomWidth: 1, borderBottomColor: color.divider }]}>
      <Text style={s.metaLabel}>{label}</Text>
      <Text style={s.metaValue} numberOfLines={1}>{value}</Text>
    </View>
  );
}

function Fact({ title, body, last }) {
  return (
    <View style={[s.fact, !last && { borderBottomWidth: 1, borderBottomColor: color.divider }]}>
      <Text style={s.factTitle}>{title}</Text>
      <Text style={s.factBody}>{body}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: color.canvas },
  rootContent: { paddingHorizontal: 16, paddingTop: 56, paddingBottom: 96 },
  authContent: { flexGrow: 1, paddingHorizontal: 24, paddingTop: 72, paddingBottom: 48, backgroundColor: color.surface },
  row: { flexDirection: 'row', alignItems: 'center' },

  brand: { fontSize: 19, fontWeight: '700', color: color.text, letterSpacing: -0.4 },
  h1: { fontSize: 27, fontWeight: '700', color: color.text, letterSpacing: -0.6 },
  lede: { fontSize: 14.5, color: color.text2, lineHeight: 22, marginTop: 8, marginBottom: 28 },
  switchText: { fontSize: 14, color: color.text2 },
  switchLink: { color: color.blue, fontWeight: '600' },
  authFacts: { marginTop: 40, borderWidth: 1, borderColor: color.border, borderRadius: radius.card, backgroundColor: color.surface2 },
  fact: { paddingHorizontal: 16, paddingVertical: 14 },
  factTitle: { fontSize: 13.5, fontWeight: '600', color: color.text },
  factBody: { fontSize: 12.5, color: color.text2, marginTop: 3, lineHeight: 18 },

  card: { backgroundColor: color.surface, borderWidth: 1, borderColor: color.border, borderRadius: radius.card, padding: 18 },
  cardTitle: { color: color.text, fontWeight: '700', fontSize: 18, letterSpacing: -0.3 },
  cardDesc: { color: color.text2, fontSize: 13, lineHeight: 19, marginTop: 6, marginBottom: 20 },
  overline: { fontSize: 11, fontWeight: '700', color: color.muted, letterSpacing: 0.8, textTransform: 'uppercase' },

  label: { color: color.text, fontSize: 13, fontWeight: '600', marginBottom: 8 },
  hint: { color: color.muted, fontSize: 12, marginTop: 6 },
  codeInput: { fontFamily: mono, fontSize: 24, letterSpacing: 8, textAlign: 'center', paddingVertical: 14 },
  input: { backgroundColor: color.surface, borderWidth: 1, borderColor: color.border, borderRadius: radius.input, paddingHorizontal: 14, paddingVertical: 12, color: color.text, fontSize: 15 },
  inputBare: { flex: 1, paddingHorizontal: 12, paddingVertical: 12, color: color.text, fontSize: 15 },
  phoneRow: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderColor: color.border, borderRadius: radius.input, backgroundColor: color.surface, overflow: 'hidden' },
  phonePrefix: { paddingHorizontal: 12, paddingVertical: 12, backgroundColor: color.surface2, color: color.text2, fontWeight: '600', fontSize: 15, borderRightWidth: 1, borderRightColor: color.border, fontFamily: mono },

  notice: { borderWidth: 1, borderRadius: radius.input, padding: 12, marginTop: 12 },
  noticeText: { fontSize: 13, lineHeight: 19, fontWeight: '500' },

  btnPrimary: { backgroundColor: color.text, paddingVertical: 15, borderRadius: radius.input, alignItems: 'center', justifyContent: 'center' },
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
  mapPreview: { height: 150, width: '100%', borderRadius: 8, overflow: 'hidden', marginTop: 10 },

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
