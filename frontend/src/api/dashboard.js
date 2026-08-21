// frontend/src/api/dashboard.js
//
// Replace the mock resolve with:
// return apiFetch(`/dashboard?principal=${principal}&from=${from}&to=${to}`).then((res) => res.json());
//
// mockDashboard.js is the only file that touches mock data — this file's
// job is just the async contract (a real Promise, with artificial latency)
// so loading states are real and testable today, and nothing above this
// file has to change when the fetch above replaces the mock resolve.
import { getMockDashboard } from './mockDashboard';

const MOCK_LATENCY_MS = 400;

export async function getDashboardData({ principal, from, to }) {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve(getMockDashboard({ principal, from, to }));
    }, MOCK_LATENCY_MS);
  });
}
