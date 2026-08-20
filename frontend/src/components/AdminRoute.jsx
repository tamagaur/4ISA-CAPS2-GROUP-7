// frontend/src/components/AdminRoute.jsx — gates admin-only pages (e.g. User
// Management) on top of ProtectedRoute's auth check. A non-admin who reaches
// this route (e.g. via a stale bookmark) is bounced to the dashboard instead
// of seeing a blank/broken admin page.
import React from 'react';
import { Navigate } from 'react-router-dom';
import { getCurrentUser } from '../auth';

const AdminRoute = ({ children }) => {
  const currentUser = getCurrentUser();

  if (currentUser?.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  return children;
};

export default AdminRoute;
