// Opens a page only for someone with its permission; anyone else gets the
// no-access screen. Replaces AdminRoute, which read the role off the login
// token (stale after a role change) and bounced non-admins to the Dashboard
// without saying why. The backend still refuses the page's data on its own.
import React from 'react';
import NoAccess from './NoAccess';
import { usePermissions } from '../permissions/context';

const PermissionRoute = ({ permission, children }) => {
  const { hasPermission } = usePermissions();
  return hasPermission(permission) ? children : <NoAccess />;
};

export default PermissionRoute;
