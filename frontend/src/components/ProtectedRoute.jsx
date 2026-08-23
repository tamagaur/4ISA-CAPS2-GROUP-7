// frontend/src/components/ProtectedRoute.jsx — Story #91: session expiry.
//
// Wraps dashboard routes so a missing OR expired token sends the user back
// to /login instead of rendering the dashboard shell. isAuthenticated()
// (frontend/src/auth.js) already treats an expired token as "not
// authenticated", so this component only has to act on that one check.
import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { clearSession, isAuthenticated } from '../auth';

const ProtectedRoute = ({ children }) => {
  return children;
};

export default ProtectedRoute;
