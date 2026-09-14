# DEPLOYMENT GUIDE: Payment Service Rollout
Document Type: DEPLOYMENT_GUIDE | Service: Payment API | Department: Platform Engineering | Version: 2.1

Pre-flight
Confirm CHG window is active. Verify ConfigMap payment-config exists in the target namespace with the expected checksum. Confirm database migration 2026_xx is applied and does not hold long locks.

Rollout steps
Set image tag in Helm values. Run helm upgrade payments ./charts/payment-api. Watch kubectl rollout status deployment/payment-api. Inspect application logs for startup exceptions during the first 10 minutes.

Validation
Verify endpoints: kubectl get endpoints payment-api. Run the synthetic checkout probe every 30 seconds. Confirm 5xx error rate stays below 0.2 percent on the payments dashboard.

Abort criteria
If HTTP 503 or CrashLoopBackOff appears on more than 10 percent of pods, immediately run kubectl rollout undo deployment/payment-api and follow RUNBOOK-005 section 5.
