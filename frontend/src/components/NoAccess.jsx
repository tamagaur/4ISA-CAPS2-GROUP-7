// Shown in place of a page the signed-in person may not open: a typed URL,
// an old bookmark, or access taken away mid-session. It used to be a silent
// bounce to the Dashboard, which looked like a broken link.
import React from 'react';
import { Link } from 'react-router-dom';
import { ShieldOff } from 'lucide-react';
import { usePermissions } from '../permissions/context';
import { PAGES } from '../permissions/keys';
import './NoAccess.css';

const NoAccess = () => {
  const { hasPermission } = usePermissions();
  const firstPage = PAGES.find((page) => hasPermission(page.permission));

  return (
    <div className="no-access-page">
      <div className="no-access-card" role="alert">
        <ShieldOff size={28} className="no-access-icon" aria-hidden="true" />
        <h2 className="no-access-title">You don&apos;t have access to this page</h2>
        <p className="no-access-text">Ask an admin if you need it.</p>
        {firstPage ? (
          <Link to={firstPage.path} className="no-access-link">Go to {firstPage.label}</Link>
        ) : (
          <p className="no-access-text">
            Your account can&apos;t open any page yet, so an admin needs to set up your access.
          </p>
        )}
      </div>
    </div>
  );
};

export default NoAccess;
