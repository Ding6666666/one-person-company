# Content Studio business plugin

This reference plugin is content only. Its manifest registers one namespaced L3
action and one declarative `调研→撰写→审核→汇总` Work Graph template. It contains
no backend module, prompt override, SQL, callback, package path, DSH runtime, or
Host lifecycle code.

The publish action is a Company declarative capability boundary, not a new DSH
runtime tool. Its final node enters the normal Core policy and approval path
only when the workspace, Employee, template node, and declared runtime profile
all grant `content-studio.publish_draft`; level 3 still requires approval before
Company dispatches work through its existing orchestration path.

Register the manifest through the public Company API, then instantiate its
template with an explicit Employee for every slot:

```ts
import {
  CompanyPluginClient,
  type BusinessPluginManifest,
} from '@dsh/company-plugin-sdk'
import manifestJson from './manifest.json' with { type: 'json' }

const client = new CompanyPluginClient(companyTransport)
await client.register(manifestJson as BusinessPluginManifest)

const work = await client.instantiate(
  'workspace-id',
  'content-studio',
  'research-write-review-summary',
  {
    command_id: 'campaign-2026-08-21',
    employee_assignments: {
      researcher: 'employee-researcher',
      writer: 'employee-writer',
      reviewer: 'employee-reviewer',
      summarizer: 'employee-summarizer',
    },
  },
)
```

`companyTransport` implements the SDK's endpoint-only `request` interface. In a
DSH Company client it can delegate to the existing `company` Typert remote; in a
standalone local integration it can call the same loopback HTTP endpoints. The
SDK does not expose Company database objects or DSH/Host lifecycle APIs.
