// Pure helpers for the donor sign-up flow, kept free of React so they can be tested with `npm test`.

export const CODE_LENGTH = 6;
export const RESEND_SECONDS = 30;

export function isValidPhone(phone) {
  return typeof phone === 'string' && /^\d{10}$/.test(phone);
}

export function isValidCode(code) {
  return typeof code === 'string' && new RegExp(`^\\d{${CODE_LENGTH}}$`).test(code.trim());
}

export function digitsOnly(value, max = CODE_LENGTH) {
  return String(value || '').replace(/\D/g, '').slice(0, max);
}

// Body for POST /api/donor/auth/register. The proof of phone ownership is sent only when there is one.
export function registerBody(phone, password, otpToken) {
  return otpToken ? { phone, password, otp_token: otpToken } : { phone, password };
}

// Plain-language message for a failed code request or check. `err` is an axios-style error.
export function codeErrorMessage(err, step) {
  const status = err?.response?.status;
  if (!status) return 'Could not reach HaemNet. Check your connection and try again.';
  if (status === 429) {
    return step === 'verify'
      ? 'Too many wrong codes. Ask for a new code and try again.'
      : 'Too many codes requested. Wait a while and try again.';
  }
  if (status === 400) return 'That code is wrong or has expired.';
  if (status === 422) return 'Enter a valid 10-digit mobile number.';
  if (status >= 500) return 'We could not send a code right now. Try again shortly.';
  return step === 'verify' ? 'Could not check the code.' : 'Could not send the code.';
}

// Seconds left before another code may be requested.
export function resendCountdown(sentAtMs, nowMs, seconds = RESEND_SECONDS) {
  if (!sentAtMs) return 0;
  return Math.max(0, Math.ceil(seconds - (nowMs - sentAtMs) / 1000));
}

// Whether the call-consent box must be ticked: only when joining, not when editing an existing profile.
export function consentRequired(isRegistered) {
  return !isRegistered;
}

// Value for `calls_consent` in the profile payload: sent when joining, left out when editing.
export function callsConsentField(isRegistered, consented) {
  return consentRequired(isRegistered) ? { calls_consent: Boolean(consented) } : {};
}
