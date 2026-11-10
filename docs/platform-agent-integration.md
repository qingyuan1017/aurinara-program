# Platform Agent Integration

Aurinara Platform is the single owner of agent registration and AgentCore invocation. An enabled
catalog entry is selectable by Aurinara only when it includes product `aurinara` and capability
`clinical_proposal_v1`. The product-facing catalog exposes the agent ID, name, description,
capabilities, and immutable catalog revision. Provider, model, Runtime ARN, qualifier, and other
Runtime metadata remain owned by Platform and are not exposed to Aurinara.

Aurinara uses its existing Cognito client-credentials identity for three calls:

```text
GET  /v1/playground/service/agents
GET  /v1/playground/service/agents/{agent_id}
POST /v1/playground/service/invocations
```

Platform derives the product from an allow-listed service client ID; callers cannot supply a product.
Proposal creation selects an `agent_id`. Aurinara resolves and freezes the current agent revision,
name, and contract version before creating the durable job. The worker submits the exact revision and
a versioned request containing module-owned system instructions, user context, output schema, and
bounded generation parameters. Platform returns a strict JSON envelope with the same agent selection,
output, response checksum, usage, and Runtime session metadata. Revision drift fails closed.

Platform forwards the same Cognito service bearer token to its AgentCore Runtime authorizer. Aurinara
never stores a Runtime ARN, never receives AgentCore IAM permission, and never accepts a caller-supplied
provider URL or model. The module still validates the returned clinical payload completely, publishes it
only as `review_required`, and requires an authorized human decision before active content changes.
