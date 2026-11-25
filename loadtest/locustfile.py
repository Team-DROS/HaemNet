"""Load test for STAGING ONLY: many hospitals raising requests at the same time.

A dispatch places REAL phone calls. Run this only against a staging backend whose Twilio account is a
trial or test account and whose donors are test numbers you own. It refuses to start otherwise.

    pip install locust
    export LOADTEST_ALLOW_REAL_CALLS=yes
    export LOADTEST_HOSPITALS='HOSP-3001:pw1,HOSP-3002:pw2'   # approved staging hospitals, id:password
    locust -f loadtest/locustfile.py --host https://<staging-api> --users 50 --spawn-rate 5 --run-time 3m --headless

Watch: p95 latency of POST /api/dispatch, error rate, 429s from the daily quota, /api/health/deep, and Sentry.
"""

import os
import random

from locust import HttpUser, between, events, task

if os.environ.get("LOADTEST_ALLOW_REAL_CALLS") != "yes":
    raise SystemExit("Refusing to run: set LOADTEST_ALLOW_REAL_CALLS=yes (staging with test donors only).")

ACCOUNTS = [a.split(":", 1) for a in os.environ.get("LOADTEST_HOSPITALS", "").split(",") if ":" in a]
if not ACCOUNTS:
    raise SystemExit("Set LOADTEST_HOSPITALS='HOSP-3001:password,HOSP-3002:password'")

GROUPS = ["O-", "O+", "A+", "B+"]


class Hospital(HttpUser):
    wait_time = between(5, 15)

    def on_start(self):
        hospital_id, password = random.choice(ACCOUNTS)
        self.hospital_id = hospital_id.strip().upper()
        res = self.client.post("/api/auth/token", data={"username": self.hospital_id, "password": password},
                               name="/api/auth/token")
        res.raise_for_status()
        self.headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

    @task(1)
    def dispatch(self):
        body = {
            "hospital_id": self.hospital_id, "blood_group": random.choice(GROUPS), "urgency": "urgent",
            "units": 1, "address": "Load test ward", "coordinates": {"lat": 13.0626, "lng": 80.2519},
        }
        with self.client.post("/api/dispatch", json=body, headers=self.headers, name="/api/dispatch",
                              catch_response=True) as res:
            if res.status_code == 429:  # the daily quota doing its job is not a failure
                res.success()

    @task(6)
    def watch(self):
        self.client.get("/api/dispatches/active", headers=self.headers, name="/api/dispatches/active")

    @task(1)
    def availability(self):
        self.client.get("/api/network/availability", headers=self.headers, name="/api/network/availability")


@events.quitting.add_listener
def _fail_on_errors(environment, **kwargs):
    stats = environment.stats.total
    if stats.fail_ratio > 0.01 or stats.get_response_time_percentile(0.95) > 3000:
        environment.process_exit_code = 1
