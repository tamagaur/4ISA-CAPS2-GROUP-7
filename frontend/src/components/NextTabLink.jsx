import React from 'react';
import { ArrowRight } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { usePermissions } from '../permissions/context';
import { nextNavItem } from '../navigation';
import './NextTabLink.css';

const NextTabLink = () => {
  const { pathname } = useLocation();
  const { hasPermission } = usePermissions();
  const next = nextNavItem(pathname, hasPermission);
  if (!next) return null;

  return (
    <nav className="next-tab" aria-label="Continue through pages">
      <Link to={next.path} className="next-tab-link">
        <span>Next: {next.name}</span>
        <ArrowRight size={15} aria-hidden="true" />
      </Link>
    </nav>
  );
};

export default NextTabLink;
