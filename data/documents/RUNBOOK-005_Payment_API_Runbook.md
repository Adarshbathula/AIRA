# RUNBOOK-005: Payment API Availability Runbook
Document Type: RUNBOOK | Service: Payment API | Department: SRE | Version: 1.2

1 Purpose and Scope
This runbook covers availability failures of the Payment API in production, including HTTP 503 responses, pod restarts and failed deployments. Owner: SRE on-call.

2 Symptoms
Payment API returns HTTP 503 (Service Unavailable). Checkout failure rate exceeds 5 percent. Kubernetes pods restart with CrashLoopBackOff or OOMKilled.

3 Pre-checks
Before applying mitigations, confirm the affected cluster and namespace, verify your kubectl context points to the production cluster and check that the on-call deployment freeze is not active.

4 Deployment Verification
Check deployment status with kubectl rollout status deployment/payment-api. Inspect application logs with kubectl logs -l app=payment-api --previous to capture the crash before restart. Verify ConfigMap availability with kubectl get configmap payment-config -n payments and compare the ConfigMap checksum against the release manifest. Validate Kubernetes service endpoints with kubectl get endpoints payment-api -n payments; an empty ENDPOINTS column means no healthy pods are registered.

5 Rollback Procedure
If a deployment is implicated, rollback with kubectl rollout undo deployment/payment-api and re-check the readiness probes. Confirm the previous image tag in the deployment history before rolling back.

6 Restart and Recovery
Restart affected Kubernetes pods with kubectl rollout restart deployment/payment-api only after configuration changes are applied. Confirm the readiness probes pass on all replicas.

7 Escalation
If the service is still unavailable after rollback and configuration verification, escalate to the Payments platform team (channel #inc-payments) and open a P1 war-room.

8 Related Documents
RCA-018 (order service database timeouts), INC-542 (previous 503 incident), SOP-API-01 (deployment validation), CHG-042 (ConfigMap management change).
