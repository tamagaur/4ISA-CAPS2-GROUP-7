// One dynamic import per routed page. App.jsx lazy-loads each page from
// these, so the login screen no longer downloads every page's code (the
// single bundle was 836 kB / 234 kB gzipped). DashboardLayout calls
// preloadPages() once the user is in, so navigating still feels instant —
// import() caches each module after its first call.
export const pageLoaders = {
  dashboard: () => import('./components/Dashboard'),
  skuManagement: () => import('./components/SKUManagement'),
  abc: () => import('./components/ABCClassification'),
  forecast: () => import('./components/SKUForecast'),
  reorder: () => import('./components/ReorderRecommendations'),
  badOrders: () => import('./components/BadOrders'),
  categoryTrends: () => import('./components/CategoryTrends'),
  auditLog: () => import('./components/AuditLog'),
  upload: () => import('./components/DataUpload'),
  users: () => import('./components/UserManagement'),
};

export function preloadPages() {
  Object.values(pageLoaders).forEach((load) => {
    load().catch(() => {
      // A failed preload is harmless: the route retries the import on visit.
    });
  });
}
