// Dynamic additions to app.json.
//
// Android push needs Firebase's google-services.json in the build. It is not committed:
// store it as an EAS file environment variable named GOOGLE_SERVICES_JSON
// (eas env:create --name GOOGLE_SERVICES_JSON --type file --visibility secret),
// or drop it next to this file for a local build. Without it the app still builds and
// runs; it just cannot receive push alerts on Android.
const fs = require('fs');
const path = require('path');

//
// Sentry: the app reports errors whenever EXPO_PUBLIC_SENTRY_DSN is set. The Sentry build plugin
// (readable stack traces through source map upload) is added only when SENTRY_ORG and
// SENTRY_PROJECT are set, with SENTRY_AUTH_TOKEN as an EAS secret, so builds without a Sentry
// account never fail on the upload step.
module.exports = ({ config }) => {
  let result = config;

  const fromEnv = process.env.GOOGLE_SERVICES_JSON;
  const local = path.join(__dirname, 'google-services.json');
  const googleServicesFile = fromEnv || (fs.existsSync(local) ? './google-services.json' : undefined);
  if (googleServicesFile) result = { ...result, android: { ...result.android, googleServicesFile } };

  const { SENTRY_ORG: organization, SENTRY_PROJECT: project } = process.env;
  if (organization && project) {
    result = { ...result, plugins: [...(result.plugins || []), ['@sentry/react-native/expo', { organization, project }]] };
  }
  return result;
};
