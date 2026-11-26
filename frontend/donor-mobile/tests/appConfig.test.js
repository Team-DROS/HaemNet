// Run with: npm test
// The app identity must belong to the team, not to one person's account.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const { expo } = JSON.parse(readFileSync(new URL('../app.json', import.meta.url), 'utf8'));
const RETIRED_OWNERS = ['umasuthan'];
const RETIRED_PROJECT_IDS = ['20aa94d4-5db2-49b8-b6f4-fa87e226806b'];

test('Android package is the team package name (permanent after the first Play upload)', () => {
  assert.equal(expo.android.package, 'in.haemnet.donor');
});

test('the app is not tied to a retired personal Expo account or project', () => {
  assert.ok(!RETIRED_OWNERS.includes(expo.owner), `owner ${expo.owner} is a retired personal account`);
  const projectId = expo.extra?.eas?.projectId;
  assert.ok(!RETIRED_PROJECT_IDS.includes(projectId), 'projectId belongs to the retired personal project');
});
