# API 契约开发规则

Company Service 与 DSH Company 插件通过明确的传输契约协作。当前契约只覆盖已实现的
工程基础，不表示 Company Domain、数据库、DSH runtime 或业务 UI 已存在。

## 权威边界

- FastAPI 中的请求、响应和错误 schema 是 API 结构的唯一权威来源。
- `packages/contracts/openapi/openapi.json` 是从 Company Service 捕获并提交的传输层快照，
  而不是另一份手工维护的 schema。
- `apps/dsh-company-plugin/src/contracts/generated/openapi.ts` 是由已提交 OpenAPI 快照
  生成的 TypeScript；禁止手工编辑。

## 捕获与可追溯性

每次捕获 OpenAPI 快照时，`packages/contracts/openapi/source-revision.json` 必须同时记录
生成该快照的 Company Service API 提交。快照、来源提交记录和生成的 TypeScript
应在同一次契约变更中保持一致。

## 兼容性变更

任何改变现有请求、响应或错误传输结构的修改，都必须显式审查兼容性影响。
不能通过直接修改 OpenAPI 快照或生成的 TypeScript 来绕过 FastAPI schema 及兼容性审查。
