const nextJest = require('next/jest');

module.exports = nextJest({ dir: './' })({
  testEnvironment: 'node',
  moduleNameMapper: { '^@/(.*)$': '<rootDir>/src/$1' },
});
