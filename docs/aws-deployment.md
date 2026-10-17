# AWS deployment and operations

## Scope

This runbook covers the CloudFormation deployment in `us-east-1`. Staging and
production are separate nested stacks in one AWS account. The design is suitable
for coded or pseudonymized clinical data under the organization's reviewed AWS
controls; it does not claim regulatory certification, a formal audit trail,
electronic signatures, PHI authorization, or regional disaster recovery.

The account bootstrap is `infra/cloudformation/bootstrap.yaml`. Each environment
uses `infra/cloudformation/environment.yaml`, which packages the network, data,
identity, compute, edge, and operations nested templates. Never deploy the parent
template without `aws cloudformation package`.

## Required inputs

Supply these values through reviewed GitHub environment variables or an approved
operator parameter file. Do not commit secrets.

- Route 53 base domain, hosted-zone ID, and a `us-east-1` ACM certificate.
- Exact GitHub owner, repository, deployment branch, and protected `staging` and
  `production` environments.
- Cognito domain prefix, verified SES source ARN/from address, and notification email.
- External platform public URL, private URL, PrivateLink endpoint-service name,
  and environment-specific SQS publisher principal.
- Digest-pinned application, Python-runner, and R-runner ECR image references.

The platform endpoint service must enable private DNS and accept the environment
VPC endpoint. Its OAuth trust must accept the Cognito service client and custom
`aurinara-platform/service` scope. Platform event delivery is at least once, so
the projection consumer remains idempotent by event ID and aggregate sequence.

## Bootstrap

Deploy the bootstrap once from an administrative session:

```powershell
aws cloudformation deploy `
  --region us-east-1 `
  --stack-name aurinara-bootstrap `
  --template-file infra/cloudformation/bootstrap.yaml `
  --capabilities CAPABILITY_NAMED_IAM `
  --parameter-overrides `
    GitHubOwner=<owner> `
    GitHubRepository=<repository> `
    DeploymentBranch=master
```

Record the deployment-role ARN, CloudFormation execution-role ARN, template
bucket, and three ECR repository outputs as GitHub environment variables. The
OIDC trust requires the exact repository, branch, and GitHub environment. Apply
GitHub Environment branch restrictions and require approval for production. No
AWS access key is stored in GitHub.

ECR repositories are immutable and scanned on push. The delivery workflow builds
the three images once per commit, creates SBOM attestations, scans the digest,
and passes the same digests through staging and production.

## Environment deployment

`.github/workflows/deploy.yml` is the authoritative release path. It packages
the nested templates, deploys staging, runs the one-off migration/catalog task,
publishes the SPA, and performs a readiness check. The production job is guarded
by GitHub Environment approval, takes an RDS snapshot, applies the reviewed
CloudFormation change set with rolling-update circuit breakers, runs only
backward-compatible migrations, publishes the SPA, enables parent-stack
termination protection, and runs the same readiness check.

Database changes use expand/contract sequencing. Application rollback means
restoring the prior image digests and redeploying the stack. It never means an
automatic database restore. If a migration needs repair, ship a forward repair
after confirming old and new application revisions can coexist with the expanded
schema.

The migration task executes:

```text
alembic upgrade head
python -m app.catalog_seed
python -m app.cdisc_registry publish-assets --verify-existing
```

Before approval, staging must pass the unit, contract, integration,
conformance, and ten end-to-end scenarios. Validate an authenticated managed
login, required TOTP enrollment, refresh and logout, uploads at configured
limits, platform projection/authorization behavior, Python/R Fargate execution,
cancellation, timeout, output and process ceilings, network denial, EFS cleanup,
and duplicate-publication fencing.

## Authentication and platform cutover

Production browser authentication is Cognito managed login using authorization
code plus PKCE. The SPA client is public and stores the maintained OIDC client's
session in browser session storage. Direct password SDK flows are a local-only
fallback and are not presented when production OIDC variables are present. The
API verifies ID tokens against the exact user-pool issuer, JWKS URL, and SPA
client audience.

Roll platform authorization in four controlled steps:

1. Deploy staging in `shadow` mode and capture mismatches without changing the
   product decision.
2. Reconcile study memberships, identity mappings, and requested scopes.
3. Run staging in `enforced` mode and verify fail-closed outages and cache
   invalidation events.
4. Change production to `enforced` in a reviewed template update.

In enforced mode a self-registered and MFA-enrolled user has no study visibility
until the platform grants membership. Backend authorization and object calls use
the private URL; only browser Repository calls use `VITE_PLATFORM_API_BASE_URL`.

## Backups and restore exercises

Production RDS retains 35 days of automated backups and is Multi-AZ. Staging
retains seven days. Artifact S3 has versioning, retained CloudFormation deletion
semantics, noncurrent-version lifecycle rules, and a daily AWS Backup selection.
The operational target is automated AZ failover, an approximately five-minute
database RPO within the backup window, and an operator-led four-hour restore RTO.

Before launch and quarterly thereafter:

1. Restore RDS to a new timestamped instance with `restore-db-instance-to-point-in-time`.
2. Attach the restored instance only to a temporary isolated validation stack;
   never point production services at it during verification.
3. Apply connectivity and integrity checks, count critical aggregates, and run a
   read-only representative workflow.
4. Restore one deleted/versioned synthetic artifact to a quarantine prefix, then
   perform an AWS Backup S3 restore to a dedicated recovery bucket.
5. Recalculate SHA-256 values and compare them with artifact metadata.
6. Record start/end times, selected recovery point, evidence, discrepancies, and
   whether the RPO/RTO targets were met. Remove temporary resources after the
   evidence is retained.

Database failover testing uses `reboot-db-instance --force-failover` during an
approved window. Confirm API retries, pool recovery, lease renewal, and absence
of duplicate publication.

## Incident runbooks

### API or deployment health failure

Inspect the CloudFormation event, ECS deployment circuit breaker, target health,
and `/health/ready`. Reapply the previous application digest values if the fault
is application-only. Do not revert migrations automatically. If RDS is impaired,
freeze writes and follow the restore runbook.

### Execution dispatcher loss

Allow the PostgreSQL lease to expire. A new claim gets a new token/generation,
stops any prior task with the same execution identity, removes that execution's
old EFS retry workspace, and starts a new digest-pinned task. The stale claimant
cannot commit terminal metadata. Investigate repeated `ExpiredLeases`, runner
task stops, and retained workspaces before manually intervening.

### Platform authorization outage

Enforced mode fails closed. Check the interface endpoint, private DNS, service
token exchange, and `PlatformAuthorizationFailures` alarm. Do not switch to
disabled mode as an availability workaround. Shadow mode is used only in the
planned cutover process.

### Projection backlog or DLQ

Check SQS oldest-message age and DLQ depth, consumer desired/running count, event
schema/version, and platform publisher policy. Redrive only after the incompatible
or poisonous message is understood. Duplicate delivery is safe; editing event
bytes is not.

### Suspected artifact compromise

Disable affected application roles, preserve CloudTrail and access logs, compare
S3 object versions and SHA-256 metadata, and prevent new packaging. Do not delete
the evidence object. Rebuild only from exact immutable inputs after incident
review.

## Secrets and launch gate

The credential-like CDISC value formerly present in `.env.example` has been
replaced with a placeholder. Before any AWS deployment, rotate that external
credential, review repository history and CI logs for exposure, invalidate every
copy, and enable GitHub secret scanning and push protection. Secrets Manager owns
database, integration-signing, and Cognito service-client secrets. Never print
resolved secret values, authorization headers, object keys, EFS paths, ECS task
ARNs, or clinical payloads in operational logs or public API responses.

Drift detection, production termination protection, clean staging replacement,
RDS/S3 restore evidence, platform PrivateLink acceptance, SES verification, alert
subscription confirmation, budget ownership, and the full staging acceptance
suite are launch gates—not post-launch cleanup.
