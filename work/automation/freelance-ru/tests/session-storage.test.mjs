import { selfTestSessionStore } from "../scripts/session-store.mjs";

const result = await selfTestSessionStore();
if (!result.roundTrip || !result.protected || result.principals.length < 3) {
  throw new Error("DPAPI storage or ACL verification failed");
}
console.log(`DPAPI storage verified at ${result.path}; ACL: ${result.principals.join(", ")}`);
