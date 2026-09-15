import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { View, Text, TextInput, TouchableOpacity, ScrollView, ActivityIndicator, StyleSheet, Linking, Platform, Image, Alert, RefreshControl } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Location from 'expo-location';
import MapView, { Marker } from 'react-native-maps';
import * as ImagePicker from 'expo-image-picker';

const COOLDOWN_DAYS = 56;
const MS_IN_A_DAY = 24 * 60 * 60 * 1000;
const DEFAULT_LAT = 12.9716;
const DEFAULT_LNG = 77.5946;

const BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-', 'Others'];
const LANGUAGES = ['English', 'Hindi', 'Tamil', 'Telugu', 'Kannada', 'Malayalam'];

export default function DonorApp() {
  // ─── AUTHENTICATION STATE ───
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [currentUser, setCurrentUser] = useState(null); // { id: 'email/phone' }
  const [authMode, setAuthMode] = useState('login'); // 'login' | 'signup'
  const [loginId, setLoginId] = useState('');
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState('');
  const [authLoading, setAuthLoading] = useState(false);

  // ─── PROFILE STATE ───
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
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

  useEffect(() => { checkLoginStatus(); }, []);
  useEffect(() => { if (isLoggedIn && currentUser) loadProfile(); }, [isLoggedIn, currentUser]);
  useEffect(() => { calculateCooldown(); }, [lastDonatedDate]);

  // ─── AUTHENTICATION ───
  const checkLoginStatus = async () => {
    try {
      const userStr = await AsyncStorage.getItem('@current_user');
      if (userStr) {
        setCurrentUser(JSON.parse(userStr));
        setIsLoggedIn(true);
      }
    } catch (e) {
      Alert.alert('Login Error', 'Error checking login status');
    }
  };

  const handleAuth = async () => {
    setAuthError('');
    if (!loginId.trim() || !password.trim()) {
      return setAuthError('Please enter both Login ID and Password');
    }
    if (loginId.trim().length !== 10 || !/^\d+$/.test(loginId.trim())) {
      return setAuthError('Mobile number must be exactly 10 digits');
    }
    setAuthLoading(true);
    try {
      const authKey = `@auth_${loginId.toLowerCase()}`;

      if (authMode === 'signup') {
        const existing = await AsyncStorage.getItem(authKey);
        if (existing) {
          setAuthError('An account with this ID already exists. Please login.');
          setAuthLoading(false);
          return;
        }
        await AsyncStorage.setItem(authKey, 'true'); // Store dummy token
        const user = { id: loginId.toLowerCase() };
        await AsyncStorage.setItem('@current_user', JSON.stringify(user));
        setCurrentUser(user);
        setIsLoggedIn(true);
      } else {
        const existing = await AsyncStorage.getItem(authKey);
        if (!existing) {
          setAuthError('No account found with this ID. Please sign up.');
          setAuthLoading(false);
          return;
        }
        // Mock authentication check
        const user = { id: loginId.toLowerCase() };
        await AsyncStorage.setItem('@current_user', JSON.stringify(user));
        setCurrentUser(user);
        setIsLoggedIn(true);
      }
    } catch (e) {
      setAuthError('Authentication error: ' + e.message);
    }
    setAuthLoading(false);
  };

  const handleLogout = async () => {
    await AsyncStorage.removeItem('@current_user');
    setIsLoggedIn(false);
    setCurrentUser(null);
    setLoginId('');
    setPassword('');
    setIsRegistered(false);
  };

  // ─── PROFILE LOGIC ───
  const getProfileKey = () => `@donor_profile_${currentUser.id}`;
  const getLogKey = () => `@donor_log_${currentUser.id}`;

  const loadProfile = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const savedProfile = await AsyncStorage.getItem(getProfileKey());
      if (savedProfile) {
        const profile = JSON.parse(savedProfile);
        setName(profile.name || '');
        setPhone(profile.phone || '');
        const loadedBg = profile.blood_group || 'O+';
        if (BLOOD_GROUPS.includes(loadedBg) && loadedBg !== 'Others') {
          setBloodGroup(loadedBg);
          setCustomBloodGroup('');
        } else {
          setBloodGroup('Others');
          setCustomBloodGroup(loadedBg);
        }

        setLanguage(profile.language || 'English');
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
        // Reset state for new user
        setName(''); setPhone(''); setBloodGroup('O+'); setCustomBloodGroup(''); setLanguage('English');
        setLat(DEFAULT_LAT); setLng(DEFAULT_LNG); setAddress(''); setLocationSource(null);
        setProfilePic(null); setLastDonatedDate(null); setIsRegistered(false);
      }

      const savedLog = await AsyncStorage.getItem(getLogKey());
      let currentLog = savedLog ? JSON.parse(savedLog) : [];

      // ─── SYNC WITH BACKEND ───
      try {
        const phoneParam = currentUser.id.startsWith('+91') ? currentUser.id : `+91${currentUser.id}`;
        const response = await axios.get(`${SERVER_BASE_URL}/api/donor/profile/${encodeURIComponent(phoneParam)}`);
        const backendProfile = response.data.donor;
        
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
            
            // Add to donation log
            const newLogEntry = {
              id: Date.now().toString(),
              date: backendProfile.last_donated_date,
              hospital: 'AI Dispatch System',
              status: 'Completed'
            };
            currentLog = [newLogEntry, ...currentLog];
            await AsyncStorage.setItem(getLogKey(), JSON.stringify(currentLog));
          }
        }
      } catch (backendErr) {
        console.log("Could not sync with backend:", backendErr.message);
      }

      setDonationLog(currentLog);
    } catch (err) {
      Alert.alert('Error', 'Failed to load profile');
    }
    if (isRefresh) setRefreshing(false);
  };

  // Hardcoded to guarantee connection (bypasses any EAS env var issues)
  // Configure EXPO_PUBLIC_API_URL per environment (EAS/local .env).
  const SERVER_BASE_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';

  const handleRegister = async () => {
    setRegError('');
    if (!name.trim()) return setRegError('Name is required');
    if (!phone.trim()) return setRegError('Phone number is required');
    if (phone.length !== 10) return setRegError('Phone number must be exactly 10 digits');
    if (!locationSource) return setRegError('Please set your location using GPS or enter it manually');

    const finalBloodGroup = bloodGroup === 'Others' ? customBloodGroup.trim() : bloodGroup;
    if (!finalBloodGroup) return setRegError('Please specify your blood group');

    const finalPhone = phone.startsWith('+91') ? phone : `+91${phone}`;

    setIsSaving(true);
    const profile = {
      name, phone: finalPhone, blood_group: finalBloodGroup, language,
      lat, lng, address, location_source: locationSource,
      profilePic,
      last_donated_date: lastDonatedDate ? lastDonatedDate.toISOString() : null,
    };
    try {
      const res = await axios.post(`${SERVER_BASE_URL}/api/donor/register`, {
        name: profile.name,
        phone: profile.phone,
        blood_group: profile.blood_group,
        language: profile.language,
        lat: profile.lat,
        lng: profile.lng
      }, {
        headers: {
          'Content-Type': 'application/json'
        }
      });
      await AsyncStorage.setItem(getProfileKey(), JSON.stringify(profile));
      setIsSaving(false); setIsRegistered(true); setIsEditing(false);
    } catch (err) {
      setIsSaving(false);
      const errorMsg = err.response ? `Backend error: ${err.response.status}` : err.message;
      setRegError(`Failed to save profile: ${errorMsg}`);
    }
  };

  const clearProfile = async () => {
    try {
      const phoneParam = currentUser.id.startsWith('+91') ? currentUser.id : `+91${currentUser.id}`;
      await axios.delete(`${SERVER_BASE_URL}/api/donor/profile/${encodeURIComponent(phoneParam)}`);
      
      await AsyncStorage.removeItem(getProfileKey());
      await AsyncStorage.removeItem(getLogKey());
      setName(''); setPhone(''); setBloodGroup('O+'); setCustomBloodGroup(''); setLanguage('English');
      setLat(DEFAULT_LAT); setLng(DEFAULT_LNG); setAddress(''); setLocationSource(null);
      setProfilePic(null); setLastDonatedDate(null); setDonationLog([]);
      setIsRegistered(false); setIsEditing(false);
      Alert.alert('Profile Deleted', 'Your profile has been removed completely.');
    } catch (err) { 
      console.error(err);
      Alert.alert('Error', 'Failed to clear profile'); 
    }
  };

  const handleNameChange = (text) => {
    const regex = /^[a-zA-Z\s]*$/;
    if (regex.test(text)) {
      setName(text);
    }
  };

  const handlePhoneChange = (text) => {
    const numericValue = text.replace(/[^0-9]/g, '');
    setPhone(numericValue.slice(0, 10));
  };

  const handleLoginIdChange = (text) => {
    // If the string is purely numeric, limit to 10 digits
    if (/^\d+$/.test(text)) {
      if (text.length <= 10) {
        setLoginId(text);
      }
    } else {
      setLoginId(text);
    }
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
          mediaTypes: ImagePicker.MediaTypeOptions.Images,
          allowsEditing: true,
          aspect: [1, 1],
          quality: 0.5,
        });
      } else {
        const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (status !== 'granted') {
          Alert.alert('Permission needed', 'Gallery permission is required to pick a photo.');
          return;
        }
        result = await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ImagePicker.MediaTypeOptions.Images,
          allowsEditing: true,
          aspect: [1, 1],
          quality: 0.5,
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
    Alert.alert(
      "Profile Picture",
      "Choose an option",
      [
        { text: "Take Photo", onPress: () => pickImage(true) },
        { text: "Choose from Gallery", onPress: () => pickImage(false) },
        { text: "Cancel", style: "cancel" }
      ]
    );
  };

  // ─── LOCATION HELPERS ───
  const requestLocation = async () => {
    setLocationLoading(true);
    setLocationError('');
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        setLocationError('Location permission denied. Please enter your address manually below.');
        setLocationLoading(false);
        return;
      }
      const location = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      const { latitude, longitude } = location.coords;
      setLat(latitude);
      setLng(longitude);

      // Removed reverseGeocodeAsync as it can cause native crashes on some Android devices
      // without proper Google Play Services. Using coordinates directly instead.
      setAddress(`${latitude.toFixed(6)}, ${longitude.toFixed(6)}`);
      setLocationSource('gps');
    } catch (err) {
      setLocationError(`Could not get location: ${err.message}. Please enter manually.`);
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

  // ─── DONATION MILESTONES & LOGGING ───
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
    const diffTime = todayMidnight.getTime() - donationMidnight.getTime();
    const diffDays = Math.floor(diffTime / MS_IN_A_DAY);
    const remaining = Math.max(0, COOLDOWN_DAYS - diffDays);
    const progress = Math.min(100, (diffDays / COOLDOWN_DAYS) * 100);
    setDaysElapsed(diffDays);
    setDaysRemaining(remaining);
    setProgressPercent(progress);
  };

  const getNextEligibleDateText = () => {
    if (!lastDonatedDate) return '';
    const eligibleDate = new Date(lastDonatedDate.getTime());
    eligibleDate.setDate(eligibleDate.getDate() + COOLDOWN_DAYS);
    return eligibleDate.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
  };


  // ─── RENDERERS ───

  if (!isLoggedIn) {
    return (
      <View style={[s.root, { justifyContent: 'center', padding: 24 }]}>
        <View style={{ alignItems: 'center', marginBottom: 40 }}>
          <View style={s.headerIcon}><Text style={{ fontSize: 32 }}>❤️</Text></View>
          <Text style={s.headerTitle}>HaemNet App</Text>
          <Text style={s.headerSub}>SIGN IN TO CONTINUE</Text>
        </View>

        <View style={s.card}>
          <Text style={s.cardTitle}>{authMode === 'login' ? 'Welcome Back' : 'Create Account'}</Text>
          <Text style={s.cardDesc}>
            {authMode === 'login' ? 'Sign in with your Email or Mobile Number.' : 'Sign up to become a lifesaver.'}
          </Text>

          <Text style={s.label}>EMAIL OR MOBILE NUMBER</Text>
          <TextInput
            value={loginId}
            onChangeText={handleLoginIdChange}
            placeholder="e.g. 9876543210 or user@email.com"
            placeholderTextColor="#cbd5e1"
            style={s.input}
            autoCapitalize="none"
          />

          <Text style={[s.label, { marginTop: 14 }]}>PASSWORD</Text>
          <TextInput
            value={password}
            onChangeText={setPassword}
            placeholder="••••••••"
            placeholderTextColor="#cbd5e1"
            secureTextEntry
            style={s.input}
          />

          {authError ? (
            <View style={s.errorBox}><Text style={s.errorText}>{authError}</Text></View>
          ) : null}

          <TouchableOpacity onPress={handleAuth} disabled={authLoading} style={[s.btnPrimary, { marginTop: 24 }]}>
            {authLoading ? <ActivityIndicator color="#fff" /> : <Text style={s.btnPrimaryText}>{authMode === 'login' ? 'LOGIN' : 'SIGN UP'}</Text>}
          </TouchableOpacity>

          <View style={s.orRow}>
            <View style={s.orLine} />
            <Text style={s.orText}>OR</Text>
            <View style={s.orLine} />
          </View>

          <TouchableOpacity style={s.btnGoogle} onPress={() => Alert.alert('Coming Soon', 'Google Sign-In integration requires backend setup.')}>
            <Text style={{ fontSize: 16, marginRight: 8 }}>G</Text>
            <Text style={s.btnGoogleText}>Continue with Google</Text>
          </TouchableOpacity>
        </View>

        <TouchableOpacity
          style={{ alignItems: 'center', marginTop: 20 }}
          onPress={() => {
            setAuthMode(authMode === 'login' ? 'signup' : 'login');
            setAuthError('');
          }}
        >
          <Text style={{ color: '#64748b', fontSize: 14, fontWeight: '600' }}>
            {authMode === 'login' ? "Don't have an account? Sign up" : "Already have an account? Login"}
          </Text>
        </TouchableOpacity>
      </View>
    );
  }

  const renderLocationPicker = () => (
    <View style={{ marginTop: 14 }}>
      <Text style={s.label}>YOUR LOCATION</Text>

      {locationSource ? (
        <View style={s.locationConfirmed}>
          <View style={[s.row, { justifyContent: 'space-between', marginBottom: 10 }]}>
            <View style={[s.row, { flex: 1, marginRight: 10 }]}>
              <Text style={{ fontSize: 16 }}>✅</Text>
              <Text style={s.locationConfirmedAddr} numberOfLines={2}>  {address || 'Location set'}</Text>
            </View>
            <TouchableOpacity onPress={clearLocation} style={s.changeBtn}>
              <Text style={s.changeBtnText}>Change</Text>
            </TouchableOpacity>
          </View>

          {locationSource === 'gps' && (
            <MapView
              style={s.mapPreview}
              initialRegion={{
                latitude: lat,
                longitude: lng,
                latitudeDelta: 0.006,
                longitudeDelta: 0.006,
              }}
              scrollEnabled={false} zoomEnabled={false} pitchEnabled={false} rotateEnabled={false}
            >
              <Marker coordinate={{ latitude: lat, longitude: lng }} title={address} />
            </MapView>
          )}
        </View>
      ) : (
        <View>
          <TouchableOpacity onPress={requestLocation} disabled={locationLoading} style={s.gpsBtn} activeOpacity={0.8}>
            {locationLoading ? (
              <View style={s.row}>
                <ActivityIndicator size="small" color="#fff" />
                <Text style={s.gpsBtnText}>  Detecting location...</Text>
              </View>
            ) : (
              <View style={s.row}>
                <Text style={{ fontSize: 18 }}>📍</Text>
                <View style={{ marginLeft: 12 }}>
                  <Text style={s.gpsBtnText}>Use My Current Location</Text>
                  <Text style={s.gpsBtnSub}>Detects via GPS</Text>
                </View>
              </View>
            )}
          </TouchableOpacity>

          {locationError ? (
            <View style={s.locationErrBox}>
              <Text style={{ fontSize: 12 }}>⚠️</Text>
              <Text style={s.locationErrText}>  {locationError}</Text>
            </View>
          ) : null}

          <View style={s.orRow}>
            <View style={s.orLine} />
            <Text style={s.orText}>or enter manually</Text>
            <View style={s.orLine} />
          </View>

          <TextInput
            value={locationSource === 'manual' ? address : (address && !locationSource ? address : '')}
            onChangeText={setAddress}
            onEndEditing={() => setLocationSource(address.trim() ? 'manual' : null)}
            placeholder="e.g. Koramangala, Bangalore 560034"
            placeholderTextColor="#cbd5e1"
            style={s.input}
            multiline
            numberOfLines={2}
          />
        </View>
      )}
    </View>
  );

  return (
    <ScrollView 
      style={s.root} 
      contentContainerStyle={s.rootContent}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={() => loadProfile(true)} colors={['#e11d48']} />
      }
    >
      <View style={s.headerWrap}>
        <View style={[s.row, { width: '100%', justifyContent: 'space-between', paddingHorizontal: 10, position: 'absolute', top: -30 }]}>
          <Text style={{ fontSize: 12, color: '#94a3b8', fontWeight: 'bold' }}>{currentUser.id}</Text>
          <TouchableOpacity onPress={handleLogout}><Text style={{ color: '#e11d48', fontSize: 12, fontWeight: 'bold' }}>Logout</Text></TouchableOpacity>
        </View>
        <View style={s.headerIcon}><Text style={{ fontSize: 28 }}>❤️</Text></View>
        <Text style={s.headerTitle}>HaemNet App</Text>
        <Text style={s.headerSub}>ACTIVE EMERGENCY DONOR NETWORK</Text>
      </View>

      {!isRegistered || isEditing ? (
        <View style={s.card}>
          <View style={s.cardTitleRow}>
            <Text style={{ fontSize: 16, marginRight: 6 }}>👤</Text>
            <Text style={s.cardTitle}>Zero-Friction Registry</Text>
          </View>
          <Text style={s.cardDesc}>Register your details to join the emergency donor network.</Text>

          <View style={{ alignItems: 'center', marginBottom: 20 }}>
            <TouchableOpacity onPress={promptImagePicker} style={s.avatarContainer}>
              {profilePic ? (
                <Image source={{ uri: profilePic }} style={s.avatarImage} />
              ) : (
                <View style={s.avatarPlaceholder}>
                  <Text style={{ fontSize: 32 }}>📷</Text>
                </View>
              )}
              <View style={s.avatarBadge}><Text style={{ fontSize: 12 }}>✏️</Text></View>
            </TouchableOpacity>
          </View>

          <Text style={s.label}>FULL NAME</Text>
          <TextInput value={name} onChangeText={handleNameChange} placeholder="e.g. Ramesh Patel" placeholderTextColor="#cbd5e1" style={s.input} />

          <Text style={[s.label, { marginTop: 14 }]}>PHONE NUMBER</Text>
          <View style={s.phoneInputContainer}>
            <View style={s.phonePrefix}><Text style={s.phonePrefixText}>+91</Text></View>
            <TextInput
              value={phone}
              onChangeText={handlePhoneChange}
              placeholder="9876543210"
              placeholderTextColor="#cbd5e1"
              keyboardType="phone-pad"
              maxLength={10}
              style={[s.input, s.phoneInput]}
            />
          </View>

          <Text style={[s.label, { marginTop: 14 }]}>BLOOD GROUP</Text>
          <View style={s.chipContainer}>
            {BLOOD_GROUPS.map(bg => (
              <TouchableOpacity
                key={bg}
                onPress={() => setBloodGroup(bg)}
                style={[s.chip, bloodGroup === bg && s.chipSelected]}
              >
                <Text style={[s.chipText, bloodGroup === bg && s.chipTextSelected]}>{bg}</Text>
              </TouchableOpacity>
            ))}
          </View>

          {bloodGroup === 'Others' && (
            <TextInput
              value={customBloodGroup}
              onChangeText={setCustomBloodGroup}
              placeholder="e.g. Bombay Blood"
              placeholderTextColor="#cbd5e1"
              style={[s.input, { marginTop: 8 }]}
            />
          )}

          <Text style={[s.label, { marginTop: 14 }]}>AI CALL LANGUAGE</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginHorizontal: -4 }}>
            {LANGUAGES.map(lang => (
              <TouchableOpacity
                key={lang}
                onPress={() => setLanguage(lang)}
                style={[s.chip, { marginHorizontal: 4 }, language === lang && s.chipSelected]}
              >
                <Text style={[s.chipText, language === lang && s.chipTextSelected]}>{lang}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          {renderLocationPicker()}

          {regError ? <View style={s.errorBox}><Text style={s.errorText}>{regError}</Text></View> : null}

          <View style={[s.row, { marginTop: 20 }]}>
            {isEditing && (
              <TouchableOpacity onPress={() => setIsEditing(false)} style={s.btnSecondary}>
                <Text style={s.btnSecondaryText}>Cancel</Text>
              </TouchableOpacity>
            )}
            <TouchableOpacity onPress={handleRegister} disabled={isSaving} style={[s.btnPrimary, { flex: 1, marginLeft: isEditing ? 10 : 0 }]}>
              {isSaving ? <ActivityIndicator size="small" color="white" /> : <Text style={s.btnPrimaryText}>{isEditing ? 'SAVE PROFILE' : 'REGISTER PROFILE'}</Text>}
            </TouchableOpacity>
          </View>
        </View>
      ) : (
        <View>
          {/* Profile card */}
          <View style={s.card}>
            <View style={[s.row, { justifyContent: 'space-between', alignItems: 'flex-start' }]}>
              <View style={[s.row, { flex: 1 }]}>
                {profilePic ? (
                  <Image source={{ uri: profilePic }} style={s.profileAvatarSm} />
                ) : (
                  <View style={s.profileAvatarSmPlaceholder}><Text style={{ fontSize: 24 }}>👤</Text></View>
                )}
                <View style={{ flex: 1, marginLeft: 12 }}>
                  <Text style={s.labelTiny}>REGISTERED PROFILE</Text>
                  <Text style={s.profileName}>{name}</Text>
                  <Text style={s.profilePhone}>{phone.startsWith('+91') ? phone : `+91 ${phone}`}</Text>
                </View>
              </View>
              <View style={s.bloodBadge}>
                <Text style={s.bloodBadgeText}>{bloodGroup}</Text>
                <Text style={s.bloodBadgeSub}>GROUP</Text>
              </View>
            </View>

            <View style={s.profileMetaRow}>
              <View style={[s.row, { flex: 1, marginRight: 8 }]}>
                <Text style={{ fontSize: 10 }}>📍</Text>
                <Text style={s.metaText} numberOfLines={1}>  {address || 'Location not set'}</Text>
              </View>
              <View style={s.langBadge}><Text style={s.langBadgeText}>{language.toUpperCase()}</Text></View>
            </View>

            <View style={[s.row, { marginTop: 14 }]}>
              <TouchableOpacity onPress={() => setIsEditing(true)} style={[s.btnSecondary, { flex: 1, marginRight: 8 }]}>
                <Text style={s.btnSecondaryText}>Edit Settings</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={clearProfile} style={s.btnDanger}>
                <Text style={s.btnDangerText}>Delete Profile</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* Cooldown tracker */}
          <View style={[s.card, { marginTop: 16 }]}>
            <View style={[s.row, { justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }]}>
              <View style={s.row}>
                <Text style={{ fontSize: 16, marginRight: 6 }}>📅</Text>
                <Text style={[s.cardTitle, { marginLeft: 0 }]}>Medical Cooldown Tracker</Text>
              </View>
              <View style={[s.statusBadge, daysRemaining === 0 ? s.statusEligible : s.statusLocked]}>
                <Text style={[s.statusBadgeText, daysRemaining === 0 ? s.statusEligibleText : s.statusLockedText]}>
                  {daysRemaining === 0 ? 'ELIGIBLE' : 'LOCKED'}
                </Text>
              </View>
            </View>

            {/* Progress bar area */}
            <View style={s.progressBox}>
              <View style={[s.row, { justifyContent: 'space-between', marginBottom: 8 }]}>
                <Text style={s.progressLabel}>Recovery Status</Text>
                <Text style={s.progressValue}>{Math.round(progressPercent)}%</Text>
              </View>
              <View style={s.progressTrack}>
                <View style={[s.progressFill, { width: `${progressPercent}%`, backgroundColor: daysRemaining === 0 ? '#10b981' : '#e11d48' }]} />
              </View>

              <View style={s.counterPanel}>
                {daysRemaining > 0 ? (
                  <>
                    <Text style={s.counterNumber}>{daysRemaining}</Text>
                    <Text style={s.counterLabel}>DAYS LOCKOUT REMAINING</Text>
                  </>
                ) : (
                  <View style={{ alignItems: 'center', paddingVertical: 8 }}>
                    <Text style={{ fontSize: 24 }}>✅</Text>
                    <Text style={s.eligibleText}>FULLY ELIGIBLE</Text>
                  </View>
                )}
              </View>
            </View>
          </View>

          {/* DONATION LOG */}
          <View style={[s.card, { marginTop: 16, paddingHorizontal: 0 }]}>
            <View style={[s.row, { paddingHorizontal: 20, marginBottom: 12 }]}>
              <Text style={{ fontSize: 16, marginRight: 6 }}>📜</Text>
              <Text style={s.cardTitle}>Donation History Log</Text>
            </View>

            {donationLog.length === 0 ? (
              <View style={{ padding: 24, alignItems: 'center' }}>
                <Text style={{ color: '#94a3b8', fontSize: 13, fontStyle: 'italic' }}>No donations recorded yet.</Text>
              </View>
            ) : (
              <View>
                {donationLog.map((log, i) => {
                  const logDate = new Date(log.date);
                  const formattedDate = logDate.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
                  const isLast = i === donationLog.length - 1;
                  return (
                    <View key={log.id} style={[s.logItem, !isLast && s.logItemBorder]}>
                      <View style={s.logItemIcon}><Text style={{ fontSize: 14 }}>🩸</Text></View>
                      <View style={{ flex: 1, marginLeft: 12 }}>
                        <Text style={s.logHospitalText}>{log.hospital}</Text>
                        <Text style={s.logDateText}>{formattedDate}</Text>
                      </View>
                      <View style={s.logBadge}><Text style={s.logBadgeText}>DONATED</Text></View>
                    </View>
                  );
                })}
              </View>
            )}
          </View>
        </View>
      )}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#f8fafc' },
  rootContent: { paddingHorizontal: 16, paddingTop: 60, paddingBottom: 120 },
  headerWrap: { alignItems: 'center', marginBottom: 28 },
  headerIcon: { height: 56, width: 56, borderRadius: 16, backgroundColor: '#e11d48', alignItems: 'center', justifyContent: 'center', marginBottom: 12, elevation: 2 },
  headerTitle: { color: '#1e293b', fontSize: 22, fontWeight: '900', letterSpacing: -0.5 },
  headerSub: { color: '#94a3b8', fontSize: 10, marginTop: 4, fontWeight: '700', letterSpacing: 2 },

  card: { backgroundColor: '#fff', borderWidth: 1, borderColor: '#e2e8f0', borderRadius: 20, padding: 20, elevation: 1 },
  cardTitleRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 10 },
  cardTitle: { color: '#1e293b', fontWeight: '800', fontSize: 16 },
  cardDesc: { color: '#64748b', fontSize: 12, lineHeight: 18, marginBottom: 16 },

  label: { color: '#64748b', fontSize: 10, fontWeight: '700', marginBottom: 6, letterSpacing: 1 },
  labelTiny: { color: '#94a3b8', fontSize: 9, fontWeight: '800', letterSpacing: 1.5 },
  input: { backgroundColor: '#fff', borderWidth: 1, borderColor: '#e2e8f0', borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, color: '#1e293b', fontWeight: '600', fontSize: 14 },

  row: { flexDirection: 'row', alignItems: 'center' },
  halfCol: { flex: 1, marginHorizontal: 4, marginTop: 14 },

  errorBox: { backgroundColor: '#fff1f2', borderWidth: 1, borderColor: '#fecdd3', padding: 12, borderRadius: 12, marginTop: 12 },
  errorText: { color: '#be123c', fontSize: 12, fontWeight: '700' },

  btnPrimary: { backgroundColor: '#e11d48', paddingVertical: 14, borderRadius: 12, alignItems: 'center', justifyContent: 'center', elevation: 1 },
  btnPrimaryText: { color: '#fff', fontSize: 13, fontWeight: '900', letterSpacing: 1 },
  btnSecondary: { flex: 1, backgroundColor: '#f1f5f9', borderWidth: 1, borderColor: '#e2e8f0', borderRadius: 12, paddingVertical: 10, alignItems: 'center' },
  btnSecondaryText: { color: '#475569', fontSize: 12, fontWeight: '700' },
  btnDanger: { backgroundColor: '#fff1f2', borderWidth: 1, borderColor: '#fecdd3', borderRadius: 12, paddingHorizontal: 16, paddingVertical: 10, alignItems: 'center' },
  btnDangerText: { color: '#e11d48', fontSize: 12, fontWeight: '700' },

  btnGoogle: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', backgroundColor: '#fff', borderWidth: 1, borderColor: '#e2e8f0', borderRadius: 12, paddingVertical: 14, marginTop: 16 },
  btnGoogleText: { color: '#1e293b', fontSize: 14, fontWeight: '700' },

  avatarContainer: { width: 90, height: 90, borderRadius: 45, backgroundColor: '#f1f5f9', justifyContent: 'center', alignItems: 'center', borderWidth: 2, borderColor: '#e2e8f0' },
  avatarPlaceholder: { justifyContent: 'center', alignItems: 'center' },
  avatarImage: { width: '100%', height: '100%', borderRadius: 45 },
  avatarBadge: { position: 'absolute', bottom: 0, right: 0, backgroundColor: '#fff', borderRadius: 12, padding: 4, borderWidth: 1, borderColor: '#e2e8f0' },

  phoneInputContainer: { flexDirection: 'row', alignItems: 'center' },
  phonePrefix: { backgroundColor: '#f1f5f9', paddingHorizontal: 12, paddingVertical: 12, borderTopLeftRadius: 12, borderBottomLeftRadius: 12, borderWidth: 1, borderColor: '#e2e8f0', borderRightWidth: 0 },
  phonePrefixText: { color: '#64748b', fontWeight: '700', fontSize: 14 },
  phoneInput: { flex: 1, borderTopLeftRadius: 0, borderBottomLeftRadius: 0 },

  chipContainer: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { backgroundColor: '#f8fafc', borderWidth: 1, borderColor: '#e2e8f0', borderRadius: 12, paddingVertical: 10, paddingHorizontal: 16 },
  chipSelected: { backgroundColor: '#e11d48', borderColor: '#e11d48' },
  chipText: { color: '#64748b', fontSize: 13, fontWeight: '700' },
  chipTextSelected: { color: '#fff' },

  gpsBtn: { backgroundColor: '#059669', borderRadius: 14, paddingVertical: 16, paddingHorizontal: 18, elevation: 2 },
  gpsBtnText: { color: '#fff', fontSize: 15, fontWeight: '800' },
  gpsBtnSub: { color: '#a7f3d0', fontSize: 11, fontWeight: '600', marginTop: 2 },
  locationErrBox: { flexDirection: 'row', alignItems: 'flex-start', backgroundColor: '#fffbeb', borderWidth: 1, borderColor: '#fde68a', padding: 12, borderRadius: 12, marginTop: 10 },
  locationErrText: { color: '#92400e', fontSize: 12, fontWeight: '600', flex: 1 },
  orRow: { flexDirection: 'row', alignItems: 'center', marginVertical: 16 },
  orLine: { flex: 1, height: 1, backgroundColor: '#e2e8f0' },
  orText: { color: '#94a3b8', fontSize: 11, fontWeight: '700', marginHorizontal: 12 },
  locationConfirmed: { backgroundColor: '#f0fdf4', borderWidth: 1, borderColor: '#bbf7d0', borderRadius: 14, padding: 14, overflow: 'hidden' },
  locationConfirmedAddr: { color: '#065f46', fontSize: 13, fontWeight: '700', flex: 1 },
  changeBtn: { backgroundColor: '#fff', borderWidth: 1, borderColor: '#e2e8f0', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 6 },
  changeBtnText: { color: '#e11d48', fontSize: 11, fontWeight: '800' },
  mapPreview: { height: 160, width: '100%', borderRadius: 12, overflow: 'hidden', marginTop: 4 },

  profileAvatarSm: { width: 50, height: 50, borderRadius: 25 },
  profileAvatarSmPlaceholder: { width: 50, height: 50, borderRadius: 25, backgroundColor: '#f1f5f9', justifyContent: 'center', alignItems: 'center', borderWidth: 1, borderColor: '#e2e8f0' },
  profileName: { color: '#1e293b', fontSize: 20, fontWeight: '900', marginTop: 2 },
  profilePhone: { color: '#64748b', fontSize: 12, marginTop: 4, fontWeight: '600' },
  bloodBadge: { backgroundColor: '#fff1f2', borderWidth: 1, borderColor: '#fecdd3', borderRadius: 16, paddingHorizontal: 16, paddingVertical: 10, alignItems: 'center' },
  bloodBadgeText: { color: '#be123c', fontWeight: '900', fontSize: 18 },
  bloodBadgeSub: { color: '#e11d48', fontSize: 8, fontWeight: '700', marginTop: 2 },

  profileMetaRow: { flexDirection: 'row', alignItems: 'center', marginTop: 16, paddingTop: 14, borderTopWidth: 1, borderTopColor: '#f1f5f9', justifyContent: 'space-between' },
  metaText: { color: '#64748b', fontSize: 11, fontWeight: '600', flex: 1 },
  langBadge: { backgroundColor: '#f8fafc', borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4, borderWidth: 1, borderColor: '#f1f5f9' },
  langBadgeText: { color: '#64748b', fontSize: 9, fontWeight: '700' },

  statusBadge: { borderRadius: 20, paddingHorizontal: 10, paddingVertical: 3, borderWidth: 1 },
  statusEligible: { backgroundColor: '#ecfdf5', borderColor: '#a7f3d0' },
  statusLocked: { backgroundColor: '#fff1f2', borderColor: '#fecdd3' },
  statusBadgeText: { fontSize: 9, fontWeight: '900', letterSpacing: 1 },
  statusEligibleText: { color: '#047857' },
  statusLockedText: { color: '#be123c' },

  progressBox: { backgroundColor: '#f8fafc', borderWidth: 1, borderColor: '#f1f5f9', borderRadius: 16, padding: 18, marginBottom: 16 },
  progressLabel: { color: '#64748b', fontSize: 12, fontWeight: '600' },
  progressValue: { color: '#334155', fontFamily: 'monospace', fontWeight: '900', fontSize: 14 },
  progressTrack: { height: 12, width: '100%', backgroundColor: '#e2e8f0', borderRadius: 999, overflow: 'hidden' },
  progressFill: { height: '100%', borderRadius: 999 },
  progressHint: { color: '#94a3b8', fontSize: 10 },
  counterPanel: { marginTop: 18, borderTopWidth: 1, borderTopColor: '#e2e8f0', paddingTop: 16, alignItems: 'center' },
  counterNumber: { color: '#e11d48', fontSize: 40, fontWeight: '900', fontFamily: 'monospace' },
  counterLabel: { color: '#64748b', fontSize: 10, fontWeight: '700', letterSpacing: 1.5, marginTop: 4 },
  eligibleText: { color: '#047857', fontWeight: '900', fontSize: 15, letterSpacing: 1, marginTop: 6 },

  logItem: { flexDirection: 'row', alignItems: 'center', paddingVertical: 14, paddingHorizontal: 20 },
  logItemBorder: { borderBottomWidth: 1, borderBottomColor: '#f1f5f9' },
  logItemIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: '#fff1f2', justifyContent: 'center', alignItems: 'center' },
  logHospitalText: { color: '#1e293b', fontSize: 14, fontWeight: '700' },
  logDateText: { color: '#64748b', fontSize: 11, marginTop: 2 },
  logBadge: { backgroundColor: '#ecfdf5', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, borderWidth: 1, borderColor: '#a7f3d0' },
  logBadgeText: { color: '#059669', fontSize: 9, fontWeight: '800' },
});
