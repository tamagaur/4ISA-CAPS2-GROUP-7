// node --test src/utils (npm test): the profile picture editor's crop maths.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  centredCrop, clampCrop, cornerAnchor, cropFromAnchor, flipCropX, maxZoom, minCropSize, moveCrop, orientedSize,
  zoomCrop, zoomOf,
} from './avatarCrop.js';

const inside = (c, W, H) => c.x >= 0 && c.y >= 0 && c.x + c.size <= W + 1e-9 && c.y + c.size <= H + 1e-9;

test('the starting crop is the largest centred square', () => {
  assert.deepEqual(centredCrop(800, 400), { x: 200, y: 0, size: 400 });
  assert.deepEqual(centredCrop(300, 600), { x: 0, y: 150, size: 300 });
});

test('a crop moved past an edge stops at it', () => {
  const c = moveCrop({ x: 100, y: 0, size: 200 }, 900, 900, 800, 400);
  assert.deepEqual(c, { x: 600, y: 200, size: 200 });
  assert.ok(inside(moveCrop({ x: 0, y: 0, size: 400 }, -50, -50, 800, 400), 800, 400));
});

test('a crop too big or too small for the picture is brought within limits', () => {
  assert.equal(clampCrop({ x: 0, y: 0, size: 900 }, 800, 400).size, 400);
  assert.equal(clampCrop({ x: 0, y: 0, size: 1 }, 800, 400).size, minCropSize(800, 400));
});

test('dragging the bottom-right corner grows the square from the top-left', () => {
  const crop = { x: 100, y: 100, size: 100 };
  const { ax, ay, dir } = cornerAnchor(crop, 'se');
  assert.deepEqual(cropFromAnchor(ax, ay, 250, 180, 800, 400, dir), { x: 100, y: 100, size: 150 });
  // past the bottom edge: as big as the room allows
  assert.deepEqual(cropFromAnchor(ax, ay, 790, 790, 800, 400, dir), { x: 100, y: 100, size: 300 });
});

test('dragging the top-left corner keeps the bottom-right corner where it was', () => {
  const crop = { x: 300, y: 200, size: 100 };
  const { ax, ay, dir } = cornerAnchor(crop, 'nw');
  const c = cropFromAnchor(ax, ay, 250, 260, 800, 400, dir);
  assert.equal(c.x + c.size, 400);
  assert.equal(c.y + c.size, 300);
  assert.equal(c.size, 150);
});

test('drawing a new crop follows the pointer in any direction and stays inside', () => {
  assert.deepEqual(cropFromAnchor(400, 200, 300, 120, 800, 400), { x: 300, y: 100, size: 100 });
  const c = cropFromAnchor(10, 10, -500, -500, 800, 400);
  assert.ok(inside(c, 800, 400));
});

test('zoom 1 is the shorter side; zooming in shrinks the crop around its centre', () => {
  const start = centredCrop(800, 400);
  assert.equal(zoomOf(start, 800, 400), 1);
  const z = zoomCrop(start, 2, 800, 400);
  assert.equal(z.size, 200);
  assert.equal(z.x + z.size / 2, 400);
  assert.ok(zoomCrop(start, 999, 800, 400).size >= minCropSize(800, 400));
  assert.ok(maxZoom(800, 400) > 1);
});

test('a flip mirrors the crop; a quarter turn swaps width and height', () => {
  assert.deepEqual(flipCropX({ x: 0, y: 0, size: 100 }, 800), { x: 700, y: 0, size: 100 });
  assert.deepEqual(orientedSize(800, 400, 90), { W: 400, H: 800 });
  assert.deepEqual(orientedSize(800, 400, 180), { W: 800, H: 400 });
});

test('a quarter turn carries the crop with the picture, and turning back restores it', async () => {
  const { rotateCrop } = await import('./avatarCrop.js');
  const crop = { x: 50, y: 20, size: 100 };
  const cw = rotateCrop(crop, 800, 400, true); // now 400 × 800
  assert.deepEqual(cw, { x: 280, y: 50, size: 100 });
  assert.ok(inside(cw, 400, 800));
  assert.deepEqual(rotateCrop(cw, 400, 800, false), crop);
});
