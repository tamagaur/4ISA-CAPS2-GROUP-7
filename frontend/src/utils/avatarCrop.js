// The profile picture editor's geometry (components/AvatarEditor.jsx). The
// crop is a square { x, y, size } in the pixels of the picture as it is
// shown, after any rotation and flip (W × H). Every function returns a crop
// that lies wholly inside the picture and is at least `min` pixels wide, so
// the saved picture never includes empty space. Tested by avatarCrop.test.js.

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

// The smallest crop: a twentieth of the shorter side, never under 16 px.
export const minCropSize = (W, H) => Math.max(16, Math.round(Math.min(W, H) * 0.05));

// The largest centred square: the starting crop, and Reset's.
export function centredCrop(W, H) {
  const size = Math.min(W, H);
  return { x: (W - size) / 2, y: (H - size) / 2, size };
}

// A crop kept inside the picture (moved back in, and shrunk if it is too
// big for it).
export function clampCrop(crop, W, H) {
  const size = clamp(crop.size, minCropSize(W, H), Math.min(W, H));
  return { x: clamp(crop.x, 0, W - size), y: clamp(crop.y, 0, H - size), size };
}

// The crop moved by (dx, dy), stopping at the picture's edges.
export const moveCrop = (crop, dx, dy, W, H) => clampCrop({ ...crop, x: crop.x + dx, y: crop.y + dy }, W, H);

// A square stretched from a fixed corner (ax, ay) towards the pointer (px,
// py): dragging a corner handle, with the opposite corner as the anchor, or
// drawing a new crop across the picture from where the drag began. `dir`
// fixes which way it grows ({ x: ±1, y: ±1 }); without it the pointer
// decides.
export function cropFromAnchor(ax, ay, px, py, W, H, dir = null) {
  const dx = dir ? dir.x : (px >= ax ? 1 : -1);
  const dy = dir ? dir.y : (py >= ay ? 1 : -1);
  const room = Math.min(dx > 0 ? W - ax : ax, dy > 0 ? H - ay : ay);
  const want = Math.max(Math.abs(px - ax), Math.abs(py - ay));
  const size = clamp(want, Math.min(minCropSize(W, H), room), room);
  return { x: dx > 0 ? ax : ax - size, y: dy > 0 ? ay : ay - size, size };
}

// The anchor and growth direction for each corner handle.
export function cornerAnchor(crop, corner) {
  const { x, y, size } = crop;
  return {
    nw: { ax: x + size, ay: y + size, dir: { x: -1, y: -1 } },
    ne: { ax: x, ay: y + size, dir: { x: 1, y: -1 } },
    sw: { ax: x + size, ay: y, dir: { x: -1, y: 1 } },
    se: { ax: x, ay: y, dir: { x: 1, y: 1 } },
  }[corner];
}

// Zoom: 1 is the largest crop (the shorter side), higher is a smaller crop.
export const maxZoom = (W, H) => Math.min(W, H) / minCropSize(W, H);
export const zoomOf = (crop, W, H) => Math.min(W, H) / crop.size;

// The crop at a zoom level, around its own centre (kept inside the picture).
export function zoomCrop(crop, zoom, W, H) {
  const size = Math.min(W, H) / clamp(zoom, 1, maxZoom(W, H));
  const cx = crop.x + crop.size / 2;
  const cy = crop.y + crop.size / 2;
  return clampCrop({ x: cx - size / 2, y: cy - size / 2, size }, W, H);
}

// A flip mirrors the crop too, so the same part of the picture stays chosen.
export const flipCropX = (crop, W) => ({ ...crop, x: W - crop.x - crop.size });
export const flipCropY = (crop, H) => ({ ...crop, y: H - crop.y - crop.size });

// The picture's shown size after a quarter-turn rotation (0, 90, 180, 270).
export const orientedSize = (w, h, rotation) => (rotation % 180 === 0 ? { W: w, H: h } : { W: h, H: w });

// A quarter turn carries the crop with the picture, so the same part stays
// chosen: clockwise, (x, y) in W × H becomes (H − y − size, x) in H × W.
export function rotateCrop(crop, W, H, clockwise) {
  return clockwise
    ? { x: H - crop.y - crop.size, y: crop.x, size: crop.size }
    : { x: crop.y, y: W - crop.x - crop.size, size: crop.size };
}
