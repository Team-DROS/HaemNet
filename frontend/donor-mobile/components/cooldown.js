// Donation cooldown maths, kept free of React so it can be unit tested.

export const COOLDOWN_DAYS = 56;
const MS_IN_A_DAY = 24 * 60 * 60 * 1000;

const midnight = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());

/**
 * Progress through the recovery window after a donation.
 * Counts whole calendar days in local time, so a donation at 23:00
 * yesterday is "1 day ago" this morning.
 */
export function cooldownProgress(lastDonatedDate, today = new Date()) {
  if (!lastDonatedDate) {
    return { daysElapsed: COOLDOWN_DAYS, daysRemaining: 0, progressPercent: 100 };
  }
  const daysElapsed = Math.round((midnight(today) - midnight(lastDonatedDate)) / MS_IN_A_DAY);
  return {
    daysElapsed,
    daysRemaining: Math.max(0, COOLDOWN_DAYS - daysElapsed),
    progressPercent: Math.max(0, Math.min(100, (daysElapsed / COOLDOWN_DAYS) * 100)),
  };
}
