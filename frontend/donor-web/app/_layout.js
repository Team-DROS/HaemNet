import React from 'react';
import { Stack } from 'expo-router';
import { initMonitoring } from '../components/monitoring';

initMonitoring();

export default function Layout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
