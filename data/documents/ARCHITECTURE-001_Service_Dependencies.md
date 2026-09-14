# ARCHITECTURE-001: Core Service Dependency Map
Document Type: ARCHITECTURE | Department: Platform Architecture | Version: 2.4

Service topology
API Gateway (nginx) routes /payments to Payment API and /orders to Order Service. Payment API depends on: PostgreSQL primary (payment_db), Redis Cache (session store), Auth Service (token validation), Kafka topic payments-events. Order Service depends on: PostgreSQL primary (orders_db), Inventory Service, Notification Service, RabbitMQ queue order-fulfilment. Payment API and Order Service share the Kubernetes cluster prod-cluster-1, namespace payments and orders respectively, behind the same load balancer.

Failure propagation
A Redis outage degrades session validation and surfaces as HTTP 503 from the API Gateway. A PostgreSQL primary failure impacts Payment API, Order Service and Billing. Auth Service latency above 200ms causes cascading gateway timeouts across all customer-facing routes. Kafka consumer lag on payments-events delays settlement but does not impact checkout availability.

Capacity boundaries
Payment API current capacity is 3200 RPS at CPU 60 percent. Order Service capacity is 2100 RPS. The shared load balancer caps at 5000 RPS; above this threshold requests are queued and start timing out.
