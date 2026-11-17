import { placesFor } from './Shell';

const hrefs = (selfHosted: boolean, admin: boolean) => placesFor(selfHosted, admin).map((place) => place.href);

it('only exposes Runner management on self-hosted builds', () => {
  expect(hrefs(false, false)).not.toContain('/runners');
  expect(hrefs(true, false)).toContain('/runners');
});

it('only exposes UHP connections to self-hosted or platform-admin navigation', () => {
  expect(hrefs(false, false)).not.toContain('/uhp');
  expect(hrefs(false, true)).toContain('/uhp');
  expect(hrefs(true, false)).toContain('/uhp');
});
