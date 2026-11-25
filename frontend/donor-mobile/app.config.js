// Dynamic additions to app.json.
//
// Android push needs Firebase's google-services.json in the build. It is not committed:
// store it as an EAS file environment variable named GOOGLE_SERVICES_JSON
// (eas env:create --name GOOGLE_SERVICES_JSON --type file --visibility secret),
// or drop it next to this file for a local build. Without it the app still builds and
// runs; it just cannot receive push alerts on Android.
const fs = require('fs');
const path = require('path');

module.exports = ({ config }) => {
  const fromEnv = process.env.GOOGLE_SERVICES_JSON;
  const local = path.join(__dirname, 'google-services.json');
  const googleServicesFile = fromEnv || (fs.existsSync(local) ? './google-services.json' : undefined);
  if (!googleServicesFile) return config;
  return { ...config, android: { ...config.android, googleServicesFile } };
};
