// The short health check a donor answers before saying yes to a request.
//
// It follows the common deferral rules in India's National Blood Transfusion Council donor
// selection guidelines, simplified to questions a donor can answer alone. It is a self-check,
// not a medical assessment: the blood bank still screens every donor before donating.
// Kept free of React so it can be tested with `npm test`; the wording lives in the i18n tables
// under `eligibility.<id>.question` and `eligibility.<id>.reason`.

export const COOLDOWN_DAYS = 56;

// `safe` is the answer that lets the donor go ahead.
export const HEALTH_QUESTIONS = [
  { id: 'well', safe: 'yes' }, //     feeling well today, no fever, cold or infection
  { id: 'age_weight', safe: 'yes' }, // 18 to 65 years old and at least 45 kg
  { id: 'medication', safe: 'no' }, //  antibiotics or other medicine in the last 7 days
  { id: 'alcohol', safe: 'no' }, //     alcohol in the last 24 hours
  { id: 'procedure', safe: 'no' }, //   tattoo, piercing or surgery in the last 12 months
  { id: 'pregnancy', safe: 'no' }, //   pregnant, breastfeeding or gave birth in the last 12 months
];

/**
 * @param {Record<string, 'yes'|'no'|undefined>} answers
 * @returns {{ complete: boolean, eligible: boolean, failed: string[] }}
 *   failed lists the ids of questions whose answer means "not today", in question order.
 */
export function evaluateAnswers(answers) {
  const given = answers && typeof answers === 'object' ? answers : {};
  const complete = HEALTH_QUESTIONS.every((q) => given[q.id] === 'yes' || given[q.id] === 'no');
  const failed = HEALTH_QUESTIONS.filter((q) => (given[q.id] === 'yes' || given[q.id] === 'no') && given[q.id] !== q.safe)
    .map((q) => q.id);
  return { complete, eligible: complete && failed.length === 0, failed };
}

/** Whole days left in the recovery window after a donation, 0 when the donor can donate. */
export function daysUntilEligible(lastDonated, now = new Date()) {
  if (!lastDonated) return 0;
  const last = lastDonated instanceof Date ? lastDonated : new Date(lastDonated);
  if (Number.isNaN(last.getTime())) return 0;
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const elapsed = Math.round((startOfDay(now) - startOfDay(last)) / (24 * 60 * 60 * 1000));
  return Math.max(0, COOLDOWN_DAYS - elapsed);
}
