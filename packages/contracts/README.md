# Company API contracts

This package owns the committed Company service OpenAPI snapshot, its source revision,
compatibility checks, and the TypeScript contract generated for the plugin. The FastAPI
application owns the API schema; generated TypeScript must not be edited by hand.

From the repository root:

```powershell
pnpm run contracts:test
pnpm run contracts:capture -- --api-commit (git rev-parse HEAD)
pnpm run contracts:generate
node packages/contracts/scripts/check-compatibility.mjs --baseline <previous.json> --candidate packages/contracts/openapi/openapi.json
```
