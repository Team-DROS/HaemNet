// "Not available this week": short breaks from automated calls that end by themselves.
// The server keeps the end time (POST /api/donor/availability); these helpers only read it.
// Kept free of React so they can be tested with `npm test`.

// Choices offered in the app, in days. The server accepts 0 to 30.
export const PAUSE_OPTIONS = [3, 7, 14];

/**
 * @param {string|null|undefined} pausedUntil ISO time from the server
 * @returns {{ paused: boolean, until: Date|null, daysLeft: number }}
 *   daysLeft rounds up, so a break ending in 2 hours still reads as 1 day.
 */
export function pauseState(pausedUntil, now = new Date()) {
  if (!pausedUntil) return { paused: false, until: null, daysLeft: 0 };
  const until = new Date(pausedUntil);
  if (Number.isNaN(until.getTime()) || until.getTime() <= now.getTime()) return { paused: false, until: null, daysLeft: 0 };
  const daysLeft = Math.ceil((until.getTime() - now.getTime()) / (24 * 60 * 60 * 1000));
  return { paused: true, until, daysLeft };
}

// The donor is callable only when calls are on and no break is running.
export function callsStatus({ optedOut, pausedUntil }, now = new Date()) {
  if (optedOut) return 'off';
  return pauseState(pausedUntil, now).paused ? 'paused' : 'on';
}
