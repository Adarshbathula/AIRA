# CHG-042: ConfigMap and Secret Management Change Request
Document Type: CHANGE_REQUEST | Department: Platform Engineering | Status: Approved | Window: 2026-01-12 22:00-23:00 UTC

Change summary
Move all Payment API environment configuration to versioned ConfigMaps (payment-config) with SealedSecrets for credentials, enforced by the deployment pipeline.

Implementation steps
Apply ConfigMap payment-config to namespaces payments and payments-canary. Update the deployment manifest to reference the ConfigMap via envFrom. Validate the Kubernetes Secret checksums against vault before rollout. Restart affected pods and verify endpoints registration.

Rollback plan
Restore deployment manifest v2.3.1 and re-apply the legacy inline env block.

Risk notes
Deployment failing to reference the new ConfigMap results in HTTP 503 due to missing environment variables (see INC-542). Post-change validation must include readiness probe success on all replicas.
