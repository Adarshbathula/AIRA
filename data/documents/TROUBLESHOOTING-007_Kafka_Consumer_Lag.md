# TROUBLESHOOTING-007: Kafka Consumer Lag and Queue Backlog
Document Type: TROUBLESHOOTING_GUIDE | Service: Notification Service, Order Service | Department: Platform

1 Identify the scope
Check consumer lag per partition with kafka-consumer-groups --describe --group notifications. Compare lag against the processing rate to estimate the catch-up time.

2 Common causes
Dead-letter loop from a poison message. Serializer incompatibility after a schema upgrade. Too few consumers for the partition count. Downstream database latency slowing commits.

3 Remediation steps
Scale the consumer group to match the partition count. Restart stalled consumers and monitor the lag trend. If a poison message is suspected, skip the offset with documentation and isolate it to the dead-letter topic. Increase the session timeout if consumers are being kicked out during GC pauses.

4 Prevention
Alert on lag greater than 60 seconds for 10 minutes. Register schema changes in the compatibility check pipeline.
