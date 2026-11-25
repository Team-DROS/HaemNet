import HospitalDashboard from '../components/HospitalDashboard';

// The public website's "Register your hospital" buttons link here. A hospital that is
// already signed in just sees its dashboard.
export default function Register() {
  return <HospitalDashboard initialMode="register" />;
}
