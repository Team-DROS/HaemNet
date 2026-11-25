import { Stack } from 'expo-router';

import ErrorBoundary from '../components/ErrorBoundary';
import { initMonitoring, withMonitoring } from '../components/monitoring';

// Before the first render, so start-up crashes are reported too (only when a DSN is configured).
initMonitoring();

function Layout() {
  return (
    <ErrorBoundary>
      <Stack screenOptions={{ headerShown: false }} />
    </ErrorBoundary>
  );
}

export default withMonitoring(Layout);
