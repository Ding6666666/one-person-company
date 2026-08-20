export { default } from './host/service.js'
export { resolveHostConfig, type Config, type ResolvedHostConfig } from './host/config.js'
export {
  CompanyHostLifecycle,
  buildChildEnvironment,
  reserveLoopbackPort,
  type HostStatus,
} from './host/lifecycle.js'
export {
  CompanyPluginService,
  type CompanyPluginOptions,
  type ManagedLifecycle,
} from './host/plugin.js'
export { createLoopbackTransport, type LoopbackTransport } from './remote.js'
export type {
  CompanyConnectionState,
  CompanyRemoteNamespace,
  CompanyRequestMethod,
  CompanyRequestPath,
  RemoteResult,
} from './remote-contract.js'
