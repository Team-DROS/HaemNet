// Cloudflare Turnstile widget (web). Renders nothing unless
// EXPO_PUBLIC_TURNSTILE_SITE_KEY is set; the backend only enforces the check
// when it has the matching secret.

import React, { useEffect, useRef } from 'react';
import { View } from 'react-native';

export const TURNSTILE_SITE_KEY = process.env.EXPO_PUBLIC_TURNSTILE_SITE_KEY || '';
const SCRIPT = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
const BOX_ID = 'haemnet-turnstile';

function loadScript() {
  return new Promise((resolve) => {
    if (typeof window === 'undefined') return resolve(false);
    if (window.turnstile) return resolve(true);
    let tag = document.querySelector(`script[src="${SCRIPT}"]`);
    if (!tag) {
      tag = document.createElement('script');
      tag.src = SCRIPT;
      tag.async = true;
      document.head.appendChild(tag);
    }
    tag.addEventListener('load', () => resolve(true));
    tag.addEventListener('error', () => resolve(false));
  });
}

export default function Turnstile({ onToken }) {
  const widget = useRef(null);
  useEffect(() => {
    if (!TURNSTILE_SITE_KEY) return undefined;
    let gone = false;
    loadScript().then((ok) => {
      if (!ok || gone || !window.turnstile || !document.getElementById(BOX_ID)) return;
      widget.current = window.turnstile.render(`#${BOX_ID}`, {
        sitekey: TURNSTILE_SITE_KEY,
        callback: (token) => onToken(token),
        'expired-callback': () => onToken(null),
        'error-callback': () => onToken(null),
      });
    });
    return () => {
      gone = true;
      if (widget.current !== null && window.turnstile) window.turnstile.remove(widget.current);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!TURNSTILE_SITE_KEY) return null;
  return <View nativeID={BOX_ID} style={{ marginBottom: 12, minHeight: 65 }} />;
}
