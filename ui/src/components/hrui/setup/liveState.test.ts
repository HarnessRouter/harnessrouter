// A task row's dot: the harness's feed first (a turn's start and end, the moment they happen), the
// card after it, which a list read can carry from before either.
import { liveStateOf } from './fmt';
import type { TraceCard } from '@/lib/revamp-data';

const card = (status: string, rid = ''): TraceCard => ({ session_id: 's1', status, last_response_id: rid } as TraceCard);
const feed = (on: boolean, rid = '') => ({ on, rid, at: Date.now() });

test('without a word from the feed, the card says', () => {
  expect(liveStateOf(card('running'), undefined)).toBe('running');
  expect(liveStateOf(card('completed'), undefined)).toBe('done');
  expect(liveStateOf(card('failed'), undefined)).toBe('failed');
});

test('a turn the feed saw start is running, whatever an older card says', () => {
  expect(liveStateOf(card('completed', 'resp_old'), feed(true, 'resp_new'))).toBe('running');
  expect(liveStateOf(card('failed', 'resp_old'), feed(true, ''))).toBe('running');
  expect(liveStateOf(card('running'), feed(true, 'resp_new'))).toBe('running');
});

test('a finished card naming the turn the feed saw start is an end the feed missed', () => {
  expect(liveStateOf(card('completed', 'resp_new'), feed(true, 'resp_new'))).toBe('done');
  expect(liveStateOf(card('failed', 'resp_new'), feed(true, 'resp_new'))).toBe('failed');
});

test('a turn that died is set right on its card, which names no turn, and the dot follows it', () => {
  expect(liveStateOf(card('failed'), feed(true, 'resp_new'))).toBe('failed');
  expect(liveStateOf(card('failed'), feed(true, ''))).toBe('failed');
  // a turn running when the page opened (the feed names none) is not ended by the turn before it
  expect(liveStateOf(card('completed', 'resp_old'), feed(true, ''))).toBe('running');
});

test('a turn the feed saw end is not running on a card read before that end', () => {
  expect(liveStateOf(card('running'), feed(false, 'resp_new'))).toBe('unknown');
  expect(liveStateOf(card('completed', 'resp_new'), feed(false, 'resp_new'))).toBe('done');
  expect(liveStateOf(card('failed', 'resp_new'), feed(false, 'resp_new'))).toBe('failed');
});
