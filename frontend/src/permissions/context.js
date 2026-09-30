// frontend/src/permissions/context.js — usePermissions(), for any component
// under <PermissionsProvider>:
//
//   const { role, hasPermission } = usePermissions();
//   if (hasPermission(P.LP_DECIDE)) ...
//
// Kept apart from PermissionsProvider.jsx so that file exports only a
// component (the react/only-export-components lint rule).
import { createContext, useContext } from 'react';

export const PermissionsContext = createContext(null);

// Outside a provider, everything is denied: hiding too much is the safe way
// for a screen to fail. The backend refuses the requests either way.
const DENY_ALL = {
  role: null,
  permissions: [],
  hasPermission: () => false,
  refresh: () => {},
};

export function usePermissions() {
  return useContext(PermissionsContext) || DENY_ALL;
}
