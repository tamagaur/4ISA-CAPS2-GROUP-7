// frontend/src/permissions/rules.js — the proposal's permission rule, so the
// admin screen can show the effect of a change before it's saved:
//
//   effective = role preset + per-user grants − per-user removals
//
// and an admin always has everything, with overrides not applying. The
// backend applies the same rule and is the one that counts; these helpers
// only preview it. `catalog` is GET /admin/permissions/catalog's body.

export function allKeys(catalog) {
  return (catalog?.permissions || []).map((permission) => permission.key);
}

// The role's default permissions, as a Set.
export function presetKeys(catalog, role) {
  const preset = catalog?.roles?.[role];
  if (role === 'admin' || preset === 'all') return new Set(allKeys(catalog));
  return new Set(Array.isArray(preset) ? preset : []);
}

// What the person can actually do, as a Set.
export function effectiveKeys(catalog, role, overrides = {}) {
  const keys = presetKeys(catalog, role);
  if (role === 'admin') return keys;
  for (const [key, granted] of Object.entries(overrides)) {
    if (granted) keys.add(key);
    else keys.delete(key);
  }
  return keys;
}

// Only the overrides that differ from the role's preset: the body PUT
// expects ("overrides only list what differs from the preset"). Changing the
// role drops any override that the new preset already covers.
export function normalizeOverrides(catalog, role, overrides = {}) {
  if (role === 'admin') return {};
  const preset = presetKeys(catalog, role);
  return Object.fromEntries(
    Object.entries(overrides).filter(([key, granted]) => preset.has(key) !== granted)
  );
}
