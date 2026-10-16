// The dashboard's greeting ("Good afternoon, Mikhaella!"), from the
// browser's own clock (the app's pinned "today", Feb 2026, is for the data
// only): morning until noon, afternoon until six, evening after.
export const greetingFor = (hour) => {
  if (hour >= 5 && hour < 12) return 'Good morning';
  if (hour >= 12 && hour < 18) return 'Good afternoon';
  return 'Good evening';
};

// The first word of the person's name ("Mikhaella Audrey Bugayong" ->
// "Mikhaella"); their email's local part if there is no name.
export const firstNameOf = (fullName, email) => {
  const first = (fullName || '').trim().split(/\s+/)[0];
  if (first) return first;
  return (email || '').split('@')[0] || '';
};
