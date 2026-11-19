import { useRef } from 'react';
import type { CSSProperties, PointerEvent, ReactNode, RefObject, WheelEvent } from 'react';

export interface WorkflowCanvasProps {
  scale: number;
  pan: { x: number; y: number };
  onScaleChange: (scale: number) => void;
  onPanChange: (pan: { x: number; y: number }) => void;
  onPanningChange?: (panning: boolean) => void;
  onBackgroundPointerDown?: () => void;
  onNodeMove?: (nodeId: string, delta: { x: number; y: number }) => void;
  viewportRef?: RefObject<HTMLDivElement | null>;
  worldRef?: RefObject<HTMLDivElement | null>;
  viewportClassName?: string;
  viewportStyle?: CSSProperties;
  worldClassName?: string;
  worldStyle?: CSSProperties;
  minScale?: number;
  maxScale?: number;
  wheelMode?: 'pan' | 'zoom';
  children: ReactNode;
}

export function WorkflowCanvas({
  scale,
  pan,
  onScaleChange,
  onPanChange,
  onPanningChange,
  onBackgroundPointerDown,
  onNodeMove,
  viewportRef,
  worldRef,
  viewportClassName = '',
  viewportStyle,
  worldClassName = '',
  worldStyle,
  minScale = 0.25,
  maxScale = 2,
  wheelMode = 'pan',
  children,
}: WorkflowCanvasProps) {
  const dragRef = useRef<{ kind: 'pan' | 'node'; nodeId?: string; clientX: number; clientY: number; lastClientX: number; lastClientY: number; originX: number; originY: number } | null>(null);
  const scaleRef = useRef(scale);
  const panRef = useRef(pan);
  scaleRef.current = scale;
  panRef.current = pan;

  const clampScale = (value: number) => Math.min(maxScale, Math.max(minScale, value));
  const zoomAt = (event: WheelEvent<HTMLDivElement>) => {
    const viewport = viewportRef?.current;
    const world = worldRef?.current;
    if (!viewport || !world) return;
    const viewportRect = viewport.getBoundingClientRect();
    const worldRect = world.getBoundingClientRect();
    const currentScale = scaleRef.current;
    const currentPan = panRef.current;
    const value = clampScale(currentScale + (event.deltaY > 0 ? -0.1 : 0.1));
    const worldX = (event.clientX - worldRect.left) / currentScale;
    const worldY = (event.clientY - worldRect.top) / currentScale;
    const naturalLeft = worldRect.left - currentPan.x;
    const naturalTop = worldRect.top - currentPan.y;
    onScaleChange(Number(value.toFixed(2)));
    onPanChange({
      x: event.clientX - worldX * value - naturalLeft,
      y: event.clientY - worldY * value - naturalTop,
    });
    void viewportRect;
  };
  const handleWheel = (event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (wheelMode === 'zoom' || event.ctrlKey || event.metaKey) {
      zoomAt(event);
      return;
    }
    onPanChange({ x: panRef.current.x - event.deltaX, y: panRef.current.y - event.deltaY });
  };
  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest('[data-workflow-node-ignore-drag]')) return;
    const node = target.closest('[data-workflow-node-id]') as HTMLElement | null;
    if (node && onNodeMove) {
      event.preventDefault();
      node.setPointerCapture(event.pointerId);
      dragRef.current = { kind: 'node', nodeId: node.dataset.workflowNodeId, clientX: event.clientX, clientY: event.clientY, lastClientX: event.clientX, lastClientY: event.clientY, originX: 0, originY: 0 };
      onPanningChange?.(true);
      return;
    }
    if (event.target !== event.currentTarget && event.target !== worldRef?.current) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { kind: 'pan', clientX: event.clientX, clientY: event.clientY, lastClientX: event.clientX, lastClientY: event.clientY, originX: panRef.current.x, originY: panRef.current.y };
    onBackgroundPointerDown?.();
    onPanningChange?.(true);
  };
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    if (drag.kind === 'node' && drag.nodeId) {
      onNodeMove?.(drag.nodeId, { x: (event.clientX - drag.lastClientX) / scaleRef.current, y: (event.clientY - drag.lastClientY) / scaleRef.current });
      drag.lastClientX = event.clientX;
      drag.lastClientY = event.clientY;
      return;
    }
    onPanChange({ x: drag.originX + event.clientX - drag.clientX, y: drag.originY + event.clientY - drag.clientY });
  };
  const endPointer = () => {
    if (!dragRef.current) return;
    dragRef.current = null;
    onPanningChange?.(false);
  };

  return <div
    ref={viewportRef}
    className={`workflow-canvas-viewport${viewportClassName ? ` ${viewportClassName}` : ''}`}
    style={viewportStyle}
    onWheel={handleWheel}
    onPointerDown={handlePointerDown}
    onPointerMove={handlePointerMove}
    onPointerUp={endPointer}
    onPointerCancel={endPointer}
    onPointerLeave={endPointer}
  >
    <div ref={worldRef} className={`workflow-canvas-world${worldClassName ? ` ${worldClassName}` : ''}`} style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`, ...worldStyle }}>
      {children}
    </div>
  </div>;
}
