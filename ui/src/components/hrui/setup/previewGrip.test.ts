// The docked preview's width: the one wanted, kept between the preview's least and what leaves the
// conversation its room beside the task list.
jest.mock('./preview-grip.css', () => ({}), { virtual: true });
import { CONVO_MIN, fitPreview, PREVIEW_DEFAULT, PREVIEW_MIN, previewMax } from './PreviewGrip';

test('the width wanted, while it fits', () => {
  expect(fitPreview(700, 1600)).toBe(700);
  expect(fitPreview(PREVIEW_DEFAULT, 0)).toBe(PREVIEW_DEFAULT);          // not measured yet
});

test('never narrower than the preview’s least', () => {
  expect(fitPreview(100, 1600)).toBe(PREVIEW_MIN);
});

test('never so wide the conversation loses its room', () => {
  const room = 1400;
  expect(previewMax(room)).toBe(room - 300 - CONVO_MIN);
  expect(fitPreview(1200, room)).toBe(room - 300 - CONVO_MIN);
  // a window too narrow for both keeps the preview at its least
  expect(fitPreview(900, 900)).toBe(PREVIEW_MIN);
});

test('nothing kept, or nonsense kept, is the first width', () => {
  expect(fitPreview(NaN, 1600)).toBe(PREVIEW_DEFAULT);
  expect(fitPreview(0, 1600)).toBe(PREVIEW_DEFAULT);
});
