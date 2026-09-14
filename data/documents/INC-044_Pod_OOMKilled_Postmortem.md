# POSTMORTEM INC-044: User Service Pods OOMKilled During Traffic Surge
Document Type: POSTMORTEM | Service: User Service | Department: SRE

What happened
User service pods were terminated with OOMKilled after a marketing campaign doubled traffic. Restarts cascaded across nodes because the memory limit (512Mi) was below the working set (800Mi).

Root Cause: memory limit misconfiguration in the Helm values file combined with an unbounded response cache that grew under load.

Resolution: raise the memory limit to 1Gi, cap the response cache at 200Mi and enable HPA on memory utilisation. Verify with kubectl top pods and check the container memory working set.

Detection gap: no alert fired on container_oom_events_total. Add an alert rule for OOMKill events per deployment.
