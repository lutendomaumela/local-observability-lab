import http from "k6/http";
import { check, sleep } from "k6";

const baseUrl = __ENV.BASE_URL || "http://nginx:8080";
const scenario = __ENV.SCENARIO || "steady";

const scenarios = {
  steady: {
    executor: "constant-vus",
    vus: 3,
    duration: __ENV.STEADY_DURATION || "45s",
  },
  "daily-wave": {
    executor: "ramping-vus",
    startVUs: 1,
    stages: [
      { duration: "10s", target: 3 },
      { duration: "10s", target: 8 },
      { duration: "15s", target: 3 },
      { duration: "10s", target: 1 },
      { duration: "10s", target: 0 },
    ],
  },
  spike: {
    executor: "ramping-vus",
    startVUs: 1,
    stages: [
      { duration: "5s", target: 2 },
      { duration: "5s", target: 12 },
      { duration: "10s", target: 12 },
      { duration: "5s", target: 1 },
      { duration: "5s", target: 0 },
    ],
  },
  "error-burst": {
    executor: "constant-vus",
    vus: 4,
    duration: "30s",
  },
};

if (!scenarios[scenario]) {
  throw new Error(`Unknown SCENARIO "${scenario}". Choose: ${Object.keys(scenarios).join(", ")}`);
}

export const options = {
  scenarios: {
    lab_traffic: {
      exec: "sendHomeRequests",
      ...scenarios[scenario],
    },
  },
};

export function setup() {
  if (scenario !== "error-burst") {
    return { chaosEnabled: false };
  }

  const response = http.post(
    `${baseUrl}/chaos`,
    JSON.stringify({ latency_ms: 250, db_delay_ms: 0, error_rate: 1 }),
    {
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Token": __ENV.CHAOS_ADMIN_TOKEN || "",
      },
    },
  );
  if (response.status !== 200) {
    throw new Error(`Could not enable error-burst chaos: HTTP ${response.status}`);
  }
  return { chaosEnabled: true };
}

export function sendHomeRequests() {
  const response = http.get(baseUrl);
  check(response, {
    "home route returns expected status": (result) =>
      result.status === (scenario === "error-burst" ? 500 : 200),
  });
  sleep(0.5);
}

export function teardown(data) {
  if (!data.chaosEnabled) {
    return;
  }

  const response = http.del(`${baseUrl}/chaos`, null, {
    headers: { "X-Admin-Token": __ENV.CHAOS_ADMIN_TOKEN || "" },
  });
  if (response.status !== 200) {
    console.error(`Could not clear error-burst chaos: HTTP ${response.status}`);
  }
}
