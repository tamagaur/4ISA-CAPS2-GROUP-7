// "Only the latest request may apply its response" (FE-2).
//
// Each call to start() returns a tag; isCurrent(tag) is true only for the most recent
// tag, until invalidate() is called. A response handler checks its tag before touching
// state, so a response from a superseded request (an earlier principal's list landing
// late) can never be applied, whatever order the network delivers them in.
export function createLatestOnly() {
  let latest = 0;
  return {
    start: () => ++latest,
    isCurrent: (tag) => tag === latest,
    invalidate: () => { latest += 1; },
  };
}
