import React, { lazy, useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import Login from './Login';
import ForgotPassword from './ForgotPassword';
import SetPassword from './SetPassword';
import ProtectedRoute from './components/ProtectedRoute';
import PermissionRoute from './components/PermissionRoute';
import NoAccess from './components/NoAccess';
import DashboardLayout from './components/DashboardLayout';
import ToastProvider from './components/ToastProvider';
import PermissionsProvider from './permissions/PermissionsProvider';
import { usePermissions } from './permissions/context';
import { P, PAGES } from './permissions/keys';
import { pageLoaders } from './pageLoaders';
import { SignInHandoff } from './components/AuthHandoff';
import './App.css';

// Pages load on demand; the Suspense boundary lives in DashboardLayout
// around its <Outlet>, so the sidebar and top bar stay put while a page's
// code arrives.
const Dashboard = lazy(pageLoaders.dashboard);
const SKUManagement = lazy(pageLoaders.skuManagement);
const ABCClassification = lazy(pageLoaders.abc);
const SKUForecast = lazy(pageLoaders.forecast);
const ReorderRecommendations = lazy(pageLoaders.reorder);
const CategoryTrends = lazy(pageLoaders.categoryTrends);
const AuditLog = lazy(pageLoaders.auditLog);
const DataUpload = lazy(pageLoaders.upload);
const UserManagement = lazy(pageLoaders.users);
// The section B cards on sample data (admin only, not in the navigation).
const PendingPreview = lazy(() => import('./components/PendingPreview'));
// Your own display name and picture, from your name in the sidebar.
const ProfilePage = lazy(() => import('./components/ProfilePage'));

const routeTitles = {
  '/login': 'SAN2 | Login',
  '/forgot-password': 'SAN2 | Reset Password',
  '/set-password': 'SAN2 | Set Password',
  '/': 'SAN2 | Dashboard',
  '/sku-management': 'SAN2 | SKU Management',
  '/abc': 'SAN2 | ABC Classification',
  '/forecast': 'SAN2 | SKU Forecast',
  '/reorder': 'SAN2 | Reorder Recommendations',
  '/audit-log': 'SAN2 | Audit Log',
  '/upload': 'SAN2 | Data Management',
  '/users': 'SAN2 | User Management',
  '/preview': 'SAN2 | Card preview (sample data)',
  '/profile': 'SAN2 | My profile',
};

function DynamicTitle() {
  const location = useLocation();

  useEffect(() => {
    document.title = routeTitles[location.pathname] || 'SAN2 | Inventory DSS';
  }, [location]);

  return null;
}

// "/" is the Dashboard for anyone who may open it. Anyone else lands on the
// first page they can open, or the no-access screen if there is none.
function HomeRoute() {
  const { hasPermission } = usePermissions();
  if (hasPermission(P.DASHBOARD_VIEW)) return <Dashboard />;
  const firstPage = PAGES.find((page) => hasPermission(page.permission));
  return firstPage ? <Navigate to={firstPage.path} replace /> : <NoAccess />;
}

// Every page is wrapped in the permission that opens it (permissions/keys.js
// PAGES); the backend refuses the page's data on its own as well.
const guard = (permission, page) => <PermissionRoute permission={permission}>{page}</PermissionRoute>;

function App() {
  return (
    <ToastProvider>
    <div className="App">
      <DynamicTitle />
      {/* The "Signing in…" screen, over the change from the login page to
          the first page and until that page has loaded. */}
      <SignInHandoff />
      <Routes>
        <Route path="/login" element={<Login />} />
        {/* Public like /login: whoever uses these has no session yet. */}
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/set-password" element={<SetPassword />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <PermissionsProvider>
                <DashboardLayout />
              </PermissionsProvider>
            </ProtectedRoute>
          }
        >
          <Route index element={<HomeRoute />} />
          <Route path="sku-management" element={guard(P.SKU_VIEW, <SKUManagement />)} />
          <Route path="abc" element={guard(P.ABC_VIEW, <ABCClassification />)} />
          <Route path="forecast" element={guard(P.FORECAST_VIEW, <SKUForecast />)} />
          <Route path="reorder" element={guard(P.LP_VIEW, <ReorderRecommendations />)} />
          <Route path="category-trends" element={guard(P.CATEGORY_TRENDS_VIEW, <CategoryTrends />)} />
          <Route path="audit-log" element={guard(P.AUDIT_LOG_VIEW, <AuditLog />)} />
          <Route path="upload" element={guard(P.UPLOAD_RUN, <DataUpload />)} />
          <Route path="users" element={guard(P.USERS_MANAGE, <UserManagement />)} />
          <Route path="preview" element={guard(P.USERS_MANAGE, <PendingPreview />)} />
          {/* Anyone signed in may edit their own profile. */}
          <Route path="profile" element={<ProfilePage />} />
        </Route>
        {/* Unknown or retired URLs land on the dashboard instead of a
            blank page. */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
    </ToastProvider>
  );
}

export default App;
