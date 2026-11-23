# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React + Vite (TypeScript), served by nginx in Kubernetes. Talks only to the unified GraphQL gateway (Strawberry) over HTTP and `graphql-transport-ws` subscriptions. Runtime config comes from `/config.js` (GraphQL URL, environment name) so one image serves dev/test/prod.

## Users

One console, two jobs, used by the same person during the day:

- **Fleet operator** (B2B fleet company): picks a station and a connector, reserves and activates a charge for a fleet wallet, watches the session and the charge, checks balances.
- **Platform engineer / SRE** (AegisVolt team): watches the health of an environment, flips feature flags per environment, inspects failed or compensated SAGAs and recovers them.

Seen on a laptop screen or shared over a video call at normal reading distance, during the final-project oral defense where the professor asks for live demos layer by layer.

## Product Purpose

AegisVolt is a cloud-native charging-management platform for electric fleets and B2B charging stations in Latin America. Charging a vehicle is a distributed transaction (SAGA) across three microservices: station-reservation (lock connector) → billing-wallet (capture payment, with surge pricing) → energy-dispatch (physically activate the charger). When a step fails the platform compensates (refund, then release). Success for the console: the operator can start a charge and see exactly which step ran, which failed and which compensation undid it, in real time, and the engineer can prove environments are isolated (flags differ per env).

## Positioning

The SAGA is visible, not hidden: every charge is a traceable transaction with a correlation id that ties the four services, the compensations and the CloudWatch logs together. Feature flags change behavior per environment without redeploying.

## Operating Context

- Three environments (dev, test, prod), each with its own namespace, DynamoDB tables and flags; the console shows which environment it is connected to.
- Flags: `ENABLE_DYNAMIC_SURGE_PRICING` (on in dev/test, off in prod), `ENABLE_FAST_CHARGE_BOOST`, `SIMULATE_CHARGER_HARDWARE_FAULT` (forces step 3 to fail → refund + release).
- SAGA statuses: STARTED, CONNECTOR_RESERVED, PAYMENT_CAPTURED, COMPLETED, COMPENSATING, COMPENSATED, FAILED, COMPENSATION_FAILED. Compensations: RELEASE_CONNECTOR, REFUND_WALLET, ABORT_CHARGER.
- Seed data: 6 Latin American stations (one connector FAULTED at SCL-PUDAHUEL-C3); demo wallets FLEET-ANDES-EXPRESS (850), FLEET-PACIFICO-LOG (240), FLEET-SIN-FONDOS (4.5). Prices per kWh by tier (STANDARD/FAST/ULTRA), America/Bogota peak hours.
- Flag changes require an admin token (`X-Admin-Token`).

## Capabilities and Constraints

- Required by the course: real-time station/connector panel; SAGA trigger flow; feature-flag visualizer per environment; transaction/compensation history panel.
- Data only through the GraphQL schema in `services/graphql-gateway/schema.graphql` (queries, mutations, subscriptions `stationsLive`, `sagasLive`, `sagaLive`, `featureFlagsLive`).
- CI expects npm scripts `lint`, `build`, `test:e2e` (Playwright, `E2E_GRAPHQL_URL`) and a `frontend/Dockerfile` serving on port 8080.

## Brand Commitments

Name: AegisVolt. UI copy in Spanish. No logo, palette or typeface is mandated.

## Evidence on Hand

All data is synthetic demo data from the seed scripts; no real customers, stations or prices exist and none may be invented as real.

## Product Principles

1. Show the transaction, not just the result: every step and every compensation is visible.
2. The environment is always obvious; never confuse dev with prod.
3. Real time by default: subscriptions over polling.
4. Failure is a first-class state, rendered as clearly as success.
