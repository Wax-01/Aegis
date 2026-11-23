export type ConnectorStatus = "AVAILABLE" | "RESERVED" | "CHARGING" | "FAULTED" | "OFFLINE";
export type ConnectorTier = "STANDARD" | "FAST" | "ULTRA";
export type SagaStatus =
  | "STARTED"
  | "CONNECTOR_RESERVED"
  | "PAYMENT_CAPTURED"
  | "COMPLETED"
  | "COMPENSATING"
  | "COMPENSATED"
  | "FAILED"
  | "COMPENSATION_FAILED";

export interface LiveSession {
  sagaId: string;
  status: string;
  powerKw: number;
  energyKwh: number;
  targetKwh: number;
  soc: number;
}

export interface Connector {
  id: string;
  stationId: string;
  connectorType: string;
  powerKw: number;
  tier: ConnectorTier;
  status: ConnectorStatus;
  sagaId: string | null;
  fleetId: string | null;
  liveSession: LiveSession | null;
}

export interface Station {
  id: string;
  name: string;
  city: string;
  country: string;
  address: string;
  availableConnectors: number;
  totalConnectors: number;
  connectors: Connector[];
}

export interface SagaStep {
  name: string;
  service: string;
  type: "ACTION" | "COMPENSATION" | string;
  status: string;
  detail: string;
  errorCode: string | null;
  at: string;
}

export interface ChargingSession {
  sagaId: string;
  status: string;
  powerKw: number;
  currentPowerKw: number;
  energyKwh: number;
  targetKwh: number;
  soc: number;
  socStart: number;
  faultCode: string | null;
  faultMessage: string | null;
  startedAt: string | null;
  endedAt: string | null;
}

export interface Saga {
  id: string;
  correlationId: string;
  environment: string;
  status: SagaStatus;
  fleetId: string;
  vehicleId: string;
  stationId: string;
  stationName: string | null;
  connectorId: string;
  connectorPowerKw: number;
  estimatedKwh: number;
  fastChargeBoost: boolean;
  amount: number | null;
  currency: string | null;
  surgeMultiplier: number | null;
  failureStep: string | null;
  failureCode: string | null;
  failureReason: string | null;
  chargingStatus: string | null;
  energyDeliveredKwh: number | null;
  flagsSnapshot: { key: string; enabled: boolean }[];
  steps: SagaStep[];
  createdAt: string;
  updatedAt: string;
  isTerminal: boolean;
  compensated: boolean;
}

export interface FeatureFlag {
  key: string;
  enabled: boolean;
  description: string;
  environment: string;
  updatedAt: string | null;
  updatedBy: string | null;
  source: string;
}

export interface Wallet {
  fleetId: string;
  name: string;
  balance: number;
  currency: string;
  updatedAt: string | null;
}

export interface WalletTransaction {
  id: string;
  type: string;
  sagaId: string | null;
  amount: number;
  currency: string;
  balanceAfter: number | null;
  reason: string | null;
  tombstone: boolean;
  createdAt: string;
}

export interface PriceQuote {
  tier: string;
  ratePerKwh: number;
  estimatedKwh: number;
  surgePricingEnabled: boolean;
  peakHour: boolean;
  surgeMultiplier: number;
  energyCost: number;
  boostFee: number;
  total: number;
  currency: string;
  localTime: string;
}

export interface ServiceHealth {
  name: string;
  status: string;
  version: string | null;
  track: string | null;
  latencyMs: number | null;
  error: string | null;
}

export interface EnvironmentInfo {
  name: string;
  version: string;
  track: string;
  instance: string;
  region: string;
  awsBackend: string;
  tables: string[];
  logGroupPrefix: string;
}
