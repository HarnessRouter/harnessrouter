// The implicit single tenant of a self-hosted instance.
//
// A self-hosted box has one operator, so there is no login and no org switching — but the
// gateway still scopes every record by org and member. Keeping real values (rather than empty
// ones) means the storage layout is identical to the hosted deployment's, which is what makes
// "push this harness to the cloud" a copy rather than a translation.
//
// Defined here rather than in lib/api.ts because both sides need them: the browser puts the org
// in query strings, and the server-side proxy pins the identity headers. One definition, so the
// two can never disagree.
export const LOCAL_ORG = 'local';
export const LOCAL_MEMBER = 'local@localhost';
