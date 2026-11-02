// The profile picture editor (Audrey, 2026-10-18: "freedom to crop and
// adjust, not just zoom"). A dialog with the whole picture and a square
// crop on it: drag the crop to move it, drag a corner to resize it, drag
// across the picture to draw a new one, scroll or use the slider to zoom,
// rotate a quarter turn either way, flip either way, Reset. A live preview
// shows the picture as the sidebar and the profile will show it.
//
// Geometry is utils/avatarCrop.js (tested). The picture is turned and
// flipped once into an off-screen canvas (at most MAX_SIDE px on its long
// side, so a 12-megapixel photo stays quick to drag over); the crop is in
// that canvas's pixels; Apply draws the crop at `outputPx` on white.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  FlipHorizontal2, FlipVertical2, RotateCcw, RotateCw, Undo2, X, ZoomIn, ZoomOut,
} from 'lucide-react';
import Modal from './Modal';
import {
  centredCrop, clampCrop, cornerAnchor, cropFromAnchor, flipCropX, flipCropY, maxZoom, moveCrop, orientedSize,
  rotateCrop, zoomCrop, zoomOf,
} from '../utils/avatarCrop';
import './AvatarEditor.css';

const MAX_SIDE = 1600;
const STAGE_MAX = 440;
const CORNERS = ['nw', 'ne', 'sw', 'se'];

// The picture turned and flipped as it is shown. Flips are in the shown
// orientation (applied after the turn), so "flip horizontal" always mirrors
// left and right on screen.
function orientedCanvas(bitmap, { rotation, flipX, flipY }) {
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const sw = Math.max(1, Math.round(bitmap.width * scale));
  const sh = Math.max(1, Math.round(bitmap.height * scale));
  const { W, H } = orientedSize(sw, sh, rotation);
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, W, H);
  ctx.translate(W / 2, H / 2);
  ctx.scale(flipX ? -1 : 1, flipY ? -1 : 1);
  ctx.rotate((rotation * Math.PI) / 180);
  ctx.drawImage(bitmap, -sw / 2, -sh / 2, sw, sh);
  return canvas;
}

const freshSettings = (bitmap) => {
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const W = Math.max(1, Math.round(bitmap.width * scale));
  const H = Math.max(1, Math.round(bitmap.height * scale));
  return { rotation: 0, flipX: false, flipY: false, crop: centredCrop(W, H) };
};

export default function AvatarEditor({ isOpen, bitmap, initial = null, outputPx = 192, onCancel, onApply }) {
  const [settings, setSettings] = useState(() => (bitmap ? initial || freshSettings(bitmap) : null));
  // A new picture (or reopening with saved settings) starts from those.
  useEffect(() => {
    if (isOpen && bitmap) setSettings(initial || freshSettings(bitmap));
  }, [isOpen, bitmap]); // eslint-disable-line react-hooks/exhaustive-deps

  const oriented = useMemo(
    () => (bitmap && settings ? orientedCanvas(bitmap, settings) : null),
    // Re-drawn only when the turn or a flip changes, not while dragging.
    [bitmap, settings?.rotation, settings?.flipX, settings?.flipY], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const W = oriented?.width ?? 1;
  const H = oriented?.height ?? 1;
  const crop = settings ? clampCrop(settings.crop, W, H) : null;

  // The stage fits the dialog's width (up to STAGE_MAX) and the picture's shape.
  const wrapRef = useRef(null);
  const [room, setRoom] = useState(STAGE_MAX);
  useEffect(() => {
    if (!isOpen || !wrapRef.current) return undefined;
    const ro = new ResizeObserver(([entry]) => setRoom(Math.min(STAGE_MAX, Math.floor(entry.contentRect.width))));
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, [isOpen]);
  const s = Math.min(room / W, room / H);

  const stageCanvasRef = useRef(null);
  useEffect(() => {
    const c = stageCanvasRef.current;
    if (!c || !oriented) return;
    c.width = W;
    c.height = H;
    c.getContext('2d').drawImage(oriented, 0, 0);
  }, [oriented, W, H, isOpen]);

  // The live preview, redrawn with every change.
  const previewRef = useRef(null);
  const smallRef = useRef(null);
  useEffect(() => {
    if (!oriented || !crop) return;
    [previewRef.current, smallRef.current].forEach((c) => {
      if (!c) return;
      const ctx = c.getContext('2d');
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, c.width, c.height);
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(oriented, crop.x, crop.y, crop.size, crop.size, 0, 0, c.width, c.height);
    });
  }, [oriented, crop?.x, crop?.y, crop?.size]); // eslint-disable-line react-hooks/exhaustive-deps

  const setCrop = useCallback((next) => setSettings((st) => (st ? { ...st, crop: next } : st)), []);

  // Pointer: a corner handle resizes from the opposite corner; inside the
  // crop moves it; anywhere else on the picture draws a new crop.
  const stageRef = useRef(null);
  const dragRef = useRef(null);
  const toPicture = (e) => {
    const r = stageRef.current.getBoundingClientRect();
    return { px: (e.clientX - r.left) / s, py: (e.clientY - r.top) / s };
  };
  const onPointerDown = (e) => {
    if (!crop || e.button > 0) return;
    e.preventDefault();
    stageRef.current.focus({ preventScroll: true });
    stageRef.current.setPointerCapture(e.pointerId);
    const { px, py } = toPicture(e);
    const corner = e.target.dataset?.corner;
    if (corner) {
      dragRef.current = { mode: 'resize', ...cornerAnchor(crop, corner) };
    } else if (px >= crop.x && px <= crop.x + crop.size && py >= crop.y && py <= crop.y + crop.size) {
      dragRef.current = { mode: 'move', start: { px, py }, from: crop };
    } else {
      dragRef.current = { mode: 'draw', ax: Math.min(Math.max(px, 0), W), ay: Math.min(Math.max(py, 0), H) };
    }
  };
  const onPointerMove = (e) => {
    const d = dragRef.current;
    if (!d) return;
    const { px, py } = toPicture(e);
    if (d.mode === 'move') setCrop(moveCrop(d.from, px - d.start.px, py - d.start.py, W, H));
    else if (d.mode === 'resize') setCrop(cropFromAnchor(d.ax, d.ay, px, py, W, H, d.dir));
    else setCrop(cropFromAnchor(d.ax, d.ay, px, py, W, H));
  };
  const endDrag = () => { dragRef.current = null; };

  const zoomBy = useCallback((factor) => {
    setSettings((st) => {
      if (!st) return st;
      const c = clampCrop(st.crop, W, H);
      return { ...st, crop: zoomCrop(c, zoomOf(c, W, H) * factor, W, H) };
    });
  }, [W, H]);

  // The mouse wheel zooms (a passive React listener can't stop the page
  // from scrolling, so this one is attached by hand).
  useEffect(() => {
    const el = stageRef.current;
    if (!el || !isOpen) return undefined;
    const onWheel = (e) => {
      e.preventDefault();
      zoomBy(e.deltaY < 0 ? 1.08 : 1 / 1.08);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [isOpen, zoomBy, oriented]);

  const onKeyDown = (e) => {
    if (!crop) return;
    const step = crop.size * (e.shiftKey ? 0.2 : 0.05);
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (moves[e.key]) {
      e.preventDefault();
      setCrop(moveCrop(crop, moves[e.key][0], moves[e.key][1], W, H));
    } else if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      zoomBy(1.1);
    } else if (e.key === '-' || e.key === '_') {
      e.preventDefault();
      zoomBy(1 / 1.1);
    }
  };

  // A quarter turn as seen on screen. With exactly one flip on, the stored
  // turn goes the other way so the picture still turns the way the button says.
  const rotate = (clockwise) => setSettings((st) => {
    const oneFlip = st.flipX !== st.flipY;
    const step = (clockwise ? 90 : -90) * (oneFlip ? -1 : 1);
    return { ...st, rotation: (st.rotation + step + 360) % 360, crop: rotateCrop(clampCrop(st.crop, W, H), W, H, clockwise) };
  });
  const flip = (axis) => setSettings((st) => (axis === 'x'
    ? { ...st, flipX: !st.flipX, crop: flipCropX(clampCrop(st.crop, W, H), W) }
    : { ...st, flipY: !st.flipY, crop: flipCropY(clampCrop(st.crop, W, H), H) }));
  const reset = () => setSettings(freshSettings(bitmap));

  const apply = () => {
    if (!oriented || !crop) return;
    const out = document.createElement('canvas');
    out.width = outputPx;
    out.height = outputPx;
    const ctx = out.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, outputPx, outputPx);
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(oriented, crop.x, crop.y, crop.size, crop.size, 0, 0, outputPx, outputPx);
    onApply({ dataUrl: out.toDataURL('image/jpeg', 0.86), settings: { ...settings, crop } });
  };

  const zoom = crop ? zoomOf(crop, W, H) : 1;
  const zMax = maxZoom(W, H);
  // Anything to reset: a turn, a flip, or a crop other than the starting one.
  const start = centredCrop(W, H);
  const changed = Boolean(settings) && (settings.rotation !== 0 || settings.flipX || settings.flipY
    || Math.abs(crop.x - start.x) > 0.5 || Math.abs(crop.y - start.y) > 0.5 || Math.abs(crop.size - start.size) > 0.5);

  return (
    <Modal
      isOpen={isOpen && Boolean(bitmap)}
      onClose={onCancel}
      label="Adjust your picture"
      overlayClassName="avatar-editor-overlay"
      containerClassName="avatar-editor"
      closeOnOverlayClick={false}
    >
      <header className="avatar-editor-head">
        <div>
          <h3>Adjust your picture</h3>
          <p>Drag the square to move it, drag a corner to resize it, or drag across the picture to draw a new one.</p>
        </div>
        <button type="button" className="avatar-editor-close" onClick={onCancel} aria-label="Close without changing">
          <X size={18} aria-hidden="true" />
        </button>
      </header>

      <div className="avatar-editor-body">
        <div className="avatar-editor-stage-wrap" ref={wrapRef}>
          {crop && (
            <div
              ref={stageRef}
              className="avatar-editor-stage"
              style={{ width: W * s, height: H * s }}
              tabIndex={0}
              role="application"
              aria-label="Crop area. Arrow keys move the square (Shift for bigger steps); plus and minus zoom."
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              onKeyDown={onKeyDown}
            >
              <canvas ref={stageCanvasRef} className="avatar-editor-image" aria-hidden="true" />
              <div
                className="avatar-editor-crop"
                style={{ left: crop.x * s, top: crop.y * s, width: crop.size * s, height: crop.size * s }}
              >
                <span className="avatar-editor-grid" aria-hidden="true" />
                {CORNERS.map((c) => (
                  <span key={c} className={`avatar-editor-handle is-${c}`} data-corner={c} aria-hidden="true" />
                ))}
              </div>
            </div>
          )}
        </div>

        <aside className="avatar-editor-side">
          <div className="avatar-editor-previews">
            <canvas ref={previewRef} width={112} height={112} className="avatar-editor-preview is-large" aria-label="Preview of your picture" role="img" />
            <div className="avatar-editor-preview-small">
              <canvas ref={smallRef} width={44} height={44} className="avatar-editor-preview is-small" aria-hidden="true" />
              <span>As in the sidebar</span>
            </div>
          </div>

          <div className="avatar-editor-group">
            <span className="avatar-editor-label">Zoom</span>
            <div className="avatar-editor-zoom">
              <button type="button" className="avatar-editor-icon" onClick={() => zoomBy(1 / 1.15)} aria-label="Zoom out" title="Zoom out" disabled={zoom <= 1.001}>
                <ZoomOut size={16} aria-hidden="true" />
              </button>
              <input
                type="range"
                min={1}
                max={zMax}
                step={0.01}
                value={zoom}
                onChange={(e) => crop && setCrop(zoomCrop(crop, Number(e.target.value), W, H))}
                aria-label="Zoom"
                aria-valuetext={`${Math.round(zoom * 100)}%`}
              />
              <button type="button" className="avatar-editor-icon" onClick={() => zoomBy(1.15)} aria-label="Zoom in" title="Zoom in" disabled={zoom >= zMax - 0.001}>
                <ZoomIn size={16} aria-hidden="true" />
              </button>
            </div>
          </div>

          <div className="avatar-editor-group">
            <span className="avatar-editor-label">Rotate and flip</span>
            <div className="avatar-editor-tools">
              <button type="button" className="avatar-editor-tool" onClick={() => rotate(false)} title="Rotate left">
                <RotateCcw size={16} aria-hidden="true" /><span>Left</span>
              </button>
              <button type="button" className="avatar-editor-tool" onClick={() => rotate(true)} title="Rotate right">
                <RotateCw size={16} aria-hidden="true" /><span>Right</span>
              </button>
              <button type="button" className={`avatar-editor-tool${settings?.flipX ? ' is-on' : ''}`} onClick={() => flip('x')} aria-pressed={Boolean(settings?.flipX)} title="Flip horizontally">
                <FlipHorizontal2 size={16} aria-hidden="true" /><span>Flip</span>
              </button>
              <button type="button" className={`avatar-editor-tool${settings?.flipY ? ' is-on' : ''}`} onClick={() => flip('y')} aria-pressed={Boolean(settings?.flipY)} title="Flip vertically">
                <FlipVertical2 size={16} aria-hidden="true" /><span>Flip</span>
              </button>
            </div>
          </div>

          <button type="button" className="avatar-editor-reset" onClick={reset} disabled={!changed} title="Reset">
            <Undo2 size={15} aria-hidden="true" />
            Reset
          </button>
        </aside>
      </div>

      <footer className="avatar-editor-foot">
        <span className="avatar-editor-note">Saved as a {outputPx} px square.</span>
        <div className="avatar-editor-actions">
          <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={apply}>Use this picture</button>
        </div>
      </footer>
    </Modal>
  );
}
