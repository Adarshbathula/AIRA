# RCA-018: Order Service Database Connection Timeouts
Document Type: RCA | Service: Order Service | Department: Database Reliability | Status: Closed

Summary
On 2026-02-11 the Order Service could not establish database connections for 41 minutes, producing HTTP 504 responses during checkout peak hours.

Timeline
02:11 p99 latency rises. 02:24 connection timeouts to the primary. 02:31 incident INC-231 declared. 02:58 mitigation applied. 03:05 service restored.

Root Cause: connection pool exhaustion combined with a failed database migration that held a lock on the orders table. The pool size (20) was below the required concurrency (64) after the scale-out event.

Contributing Factors: The Flyway migration acquired ACCESS EXCLUSIVE locks. Autoscaling increased pod count without increasing max_connections on PostgreSQL. Monitoring did not alert on pool saturation.

Resolution: Re-run migration 2026_04 offline, increase the application connection pool to 64, raise PostgreSQL max_connections to 200 and kill the long-running transactions.

Corrective Actions: Add pool-saturation alerting (p95 connections > 80 percent). Gate autoscaling on database capacity. Require lock timeouts on migrations.

Similar Historical Incidents: INC-231, INC-904, INC-1042.
