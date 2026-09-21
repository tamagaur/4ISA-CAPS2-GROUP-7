import React, { lazy, useEffect } from 'react';
import { Routes, Route, useLocation } from 'react-router-dom';
import Login from './Login';
import ProtectedRoute from './components/ProtectedRoute';
import AdminRoute from './components/AdminRoute';
import DashboardLayout from './components/DashboardLayout';
import ToastProvider from './components/ToastProvider';
import { pageLoaders } from './pageLoaders';
import './App.css';

// Pages load on demand; the Suspense boundary lives in DashboardLayout
// around its <Outlet>, so the sidebar and top bar stay put while a page's
// code arrives.
const Dashboard = lazy(pageLoaders.dashboard);
const SKUManagement = lazy(pageLoaders.skuManagement);
const ABCClassification = lazy(pageLoaders.abc);
const SKUForecast = lazy(pageLoaders.forecast);
const ReorderRecommendations = lazy(pageLoaders.reorder);
const AuditLog = lazy(pageLoaders.auditLog);
const DataUpload = lazy(pageLoaders.upload);
const UserManagement = lazy(pageLoaders.users);

const routeTitles = {
  '/login': 'SAN2 | Login',
  '/': 'SAN2 | Dashboard',
  '/sku-management': 'SAN2 | SKU Management',
  '/abc': 'SAN2 | ABC Classification',
  '/forecast': 'SAN2 | SKU Forecast',
  '/reorder': 'SAN2 | Reorder Recommendations',
  '/audit-log': 'SAN2 | Audit Log',
  '/upload': 'SAN2 | Data Management',
  '/users': 'SAN2 | User Management',
};

function DynamicTitle() {
  const location = useLocation();

  useEffect(() => {
    document.title = routeTitles[location.pathname] || 'SAN2 | Inventory DSS';
  }, [location]);

  return null;
}

function App() {
  return (
    <ToastProvider>
    <div className="App">
      <DynamicTitle />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <DashboardLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="sku-management" element={<SKUManagement />} />
          <Route path="abc" element={<ABCClassification />} />
          <Route path="forecast" element={<SKUForecast />} />
          <Route path="reorder" element={<ReorderRecommendations />} />
          <Route
            path="audit-log"
            element={
              <AdminRoute>
                <AuditLog />
              </AdminRoute>
            }
          />
          <Route path="upload" element={<DataUpload />} />
          <Route
            path="users"
            element={
              <AdminRoute>
                <UserManagement />
              </AdminRoute>
            }
          />
        </Route>
      </Routes>
    </div>
    </ToastProvider>
  );
}

export default App;
