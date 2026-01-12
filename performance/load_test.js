import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 20 }, // Ramp up to 20 users
    { duration: '1m', target: 20 },  // Stay at 20 users
    { duration: '30s', target: 0 },  // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'], // 95% of requests must complete below 500ms
  },
};

const BASE_URL = 'http://localhost:8000';

export default function () {
  // 1. Health Check
  const resSuccess = http.get(`${BASE_URL}/health`);
  check(resSuccess, { 'status is 200': (r) => r.status === 200 });

  // 2. Dashboard Stats (Simulate load)
  // Mock auth headers would be needed for real protected endpoints
  // const params = { headers: { 'Authorization': 'Bearer ...' } };
  
  // Sleep to simulate user think time
  sleep(1);
}
