/** @jest-environment jsdom */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ToastHost, toast, toastMs } from './toast';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('toast', () => {
  it('a short line stays 2.6 s; a longer one longer, never more than 8 s', () => {
    expect(toastMs('Saved.')).toBe(2600);
    expect(toastMs('x'.repeat(40))).toBe(2600);
    const refusal = "Its plugin.json is not valid JSON. Expected ',' or '}' after property value in JSON at position 12 (line 1 column 13)";
    expect(toastMs(refusal)).toBe(2600 + 40 * (refusal.length - 40));
    expect(toastMs('x'.repeat(1000))).toBe(8000);
  });

  it('a long refusal is still on screen after 2.6 s, and gone after its own time', () => {
    jest.useFakeTimers();
    const el = document.createElement('div');
    document.body.appendChild(el);
    const root: Root = createRoot(el);
    act(() => { root.render(<ToastHost />); });
    const said = 'Its plugin.json is not valid JSON. Expected double-quoted property name in JSON at position 17 (line 3 column 1)';
    act(() => { toast(said); });
    const box = () => el.querySelector('.toast') as HTMLElement;
    expect(box().hidden).toBe(false);
    expect(box().textContent).toBe(said);
    act(() => { jest.advanceTimersByTime(2700); });
    expect(box().hidden).toBe(false);
    act(() => { jest.advanceTimersByTime(toastMs(said) - 2700 + 10); });
    expect(box().hidden).toBe(true);
    act(() => { root.unmount(); });
    el.remove();
    jest.useRealTimers();
  });
});
