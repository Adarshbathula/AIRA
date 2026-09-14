# KB-013: Diagnosing Kubernetes CrashLoopBackOff
Document Type: KNOWLEDGE_BASE | Department: SRE

CrashLoopBackOff means the kubelet keeps restarting a container that exits at startup. Inspect the exit code first: 137 indicates OOMKilled (raise memory limit), 1 usually means application exception, 255 a node runtime issue.

Describe the pod and read events: kubectl describe pod shows the failing probe or image pull error. Check the previous container logs: kubectl logs --previous. Common root causes: missing ConfigMap or Secret key, bad liveness probe timing, image pull policy mismatch, init container failure, read-only filesystem permission error.

Recovery: fix the configuration, re-apply the manifest, and restart affected pods. Verify with kubectl get events -n <ns> --sort-by=.lastTimestamp and confirm all replicas pass readiness before closing the incident.
