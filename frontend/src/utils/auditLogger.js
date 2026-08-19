import { getCurrentUser } from '../auth';

const AUDIT_LOG_KEY = 'san2_audit_log';

const INITIAL_LOGS = [];

export const getAuditLogs = () => {
  const stored = localStorage.getItem(AUDIT_LOG_KEY);
  if (!stored) {
    localStorage.setItem(AUDIT_LOG_KEY, JSON.stringify(INITIAL_LOGS));
    return INITIAL_LOGS;
  }
  try {
    return JSON.parse(stored);
  } catch (err) {
    return INITIAL_LOGS;
  }
};
export const logAction = (action, details) => {
  const currentUser = getCurrentUser();
  const userName = currentUser?.fullName || currentUser?.email || 'System';
  const role = currentUser?.role ? currentUser.role.toUpperCase() : 'USER';
  const email = currentUser?.email || (userName.toLowerCase().replace(/\s+/g, '.') + '@san2.local');
  
  const newLog = {
    id: Date.now().toString(),
    timestamp: new Date().toISOString(),
    user: userName,
    email: email,
    role: role,
    action,
    details
  };

  const currentLogs = getAuditLogs();
  const updatedLogs = [newLog, ...currentLogs]; // prepend
  localStorage.setItem(AUDIT_LOG_KEY, JSON.stringify(updatedLogs));
  
  return newLog;
};
