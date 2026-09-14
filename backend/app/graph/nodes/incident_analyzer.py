"""Incident Analyzer node.

Extracts service / error / environment / event / symptoms / severity /
category / retrieval keywords. Hybrid: deterministic regex+lexicon extraction
first (always available, never hallucinates), optional LLM merge afterwards
(confined to the input text + canonical vocabularies).
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.graph.nodes import llm_of, settings_of
from app.rag.grading.lexicon import STOPWORDS, _TOKEN_RE, content_tokens
from app.schemas.incident import IncidentAnalysis

# ------------------------------------------------------------------ lexicons
SERVICE_ALIASES: dict[str, str] = {
    "payment api": "Payment API", "payment-api": "Payment API", "paymentapi": "Payment API", "payments": "Payment API",
    "payment gateway": "Payment Gateway",
    "order service": "Order Service", "order-service": "Order Service", "orders service": "Order Service",
    "user service": "User Service", "user-service": "User Service", "profile service": "User Service",
    "auth service": "Auth Service", "auth-service": "Auth Service", "login service": "Auth Service",
    "sso": "Auth Service",
    "inventory service": "Inventory Service", "cart service": "Cart Service",
    "notification service": "Notification Service", "email service": "Notification Service",
    "search service": "Search Service", "recommendation service": "Recommendation Service",
    "shipping service": "Shipping Service", "catalog service": "Catalog Service",
    "checkout service": "Checkout Service", "billing service": "Billing Service",
    "api gateway": "API Gateway", "ingress": "API Gateway",
    "redis": "Redis Cache", "memcached": "Cache Layer", "kafka": "Kafka Broker",
    "rabbitmq": "RabbitMQ", "elasticsearch": "Elasticsearch",
    "postgres": "PostgreSQL Database", "postgresql": "PostgreSQL Database", "database": "PostgreSQL Database",
    "db": "PostgreSQL Database", "mysql": "MySQL Database", "mongodb": "MongoDB",
    "nginx": "Nginx", "load balancer": "Load Balancer", "cdn": "CDN",
    "frontend": "Web Frontend", "webapp": "Web Frontend", "mobile api": "Mobile API",
    "kubernetes": "Kubernetes Cluster", "k8s": "Kubernetes Cluster", "cluster": "Kubernetes Cluster",
    "node": "Compute Node", "server": "Application Server", "vm": "Virtual Machine",
    "queue": "Message Queue", "worker": "Worker Service", "cron": "Scheduler Service",
}

ERROR_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:http\s*)?(5\d\d)\b", "HTTP {0}"),
    (r"\b(?:http\s*)?(429)\b", "HTTP 429 (rate limited)"),
    (r"\b(?:http\s*)?(401|403)\b", "HTTP {0}"),
    (r"503.{0,30}service unavailable|service unavailable", "HTTP 503 (Service Unavailable)"),
    (r"oom[\s-]?killed|out of memory", "OOMKilled"),
    (r"crashloopbackoff", "CrashLoopBackOff"),
    (r"imagepullbackoff", "ImagePullBackOff"),
    (r"connection (timed out|timeout|refused|reset)", "Connection {0}"),
    (r"connection ?pool (exhausted|saturation)|pool exhaustion", "Connection pool exhaustion"),
    (r"(too many connections)", "PostgreSQL {0}"),
    (r"deadlock detected|deadlock", "Database deadlock"),
    (r"disk (utilization|usage|full).{0,20}\d\d%|\d\d% disk", "Disk saturation"),
    (r"cpu.{0,30}(9\d%|exceed|high|saturat|throttl)|high cpu", "High CPU utilization"),
    (r"memory (pressure|leak).{0,20}\d\d%", "Memory pressure"),
    (r"\btimeout\b|timed out", "Timeout"),
    (r"latency.{0,20}(spike|high)|slow responses?|\bp99\b", "Elevated latency"),
    (r"(certificate|cert) expired", "Expired certificate"),
    (r"unable to (log ?in|authenticate)|login (failures?|broken)|cannot log ?in", "Authentication failure"),
    (r"pod.{0,30}(evicted|terminated)", "Pod eviction"),
    (r"node.{0,15}notready|not ready", "Node NotReady"),
    (r"\b404\b", "HTTP 404"),
]

SEVERITY_RULES: list[tuple[str, str]] = [
    (r"\bp0\b|full outage|complete outage|site down|all traffic|total outage", "P0"),
    (r"\bp1\b|production down|critical|customer[- ]facing outage|no payment", "P1"),
    (r"\bp2\b|degrad|intermittent|partial|customer complaints|high error rate|503", "P2"),
    (r"\bp3\b|minor|cosmetic|one pod|single node", "P3"),
    (r"\bp4\b", "P4"),
]

EVENT_RULES: list[tuple[str, str]] = [
    (r"after.{0,30}(deploy|release|rollout|upgrade|migration|change)|(deploy|release|rollout)\b.{0,20}(broke|after|since)", "Deployment"),
    (r"config(?:uration)? chang|new config|configmap|changed (?:the )?(?:env|config)", "Configuration Change"),
    (r"traffic spike|sudden (?:surge|increase)|marketing campaign|flash sale", "Traffic Surge"),
    (r"failover|primary (?:went down|switched)|replica promotion", "Failover"),
    (r"cert(?:ificate)? (?:expir|rotat)|key rotation", "Certificate Rotation"),
    (r"scaling event|resiz|hpa|autoscal", "Scaling"),
    (r"network (?:change|policy)|firewall rule|security group", "Network Change"),
]

CATEGORY_RULES: dict[str, list[str]] = {
    "Database": [r"database", r"\bdb\b", r"postgres", r"mysql", r"query", r"deadlock", r"replica", r"migration", r"connection pool"],
    "Kubernetes / Container": [r"kubernetes", r"\bk8s\b", r"\bpod", r"crashloop", r"container", r"kubectl", r"namespace", r"helm", r"node.?ready", r"deployment manifest"],
    "Compute / Resource": [r"\bcpu\b", r"\bmemory\b", r"oom", r"disk", r"inode", r"load average", r"swap"],
    "Network": [r"network", r"dns", r"firewall", r"latency", r"packet loss", r"routing", r"load balancer", r"tls", r"timeout intermitt", r"unreachable"],
    "Security / Auth": [r"login", r"auth", r"\bsso\b", r"token", r"certificate", r"permission", r"unauthorized", r"forbidden"],
    "Middleware": [r"queue", r"kafka", r"rabbitmq", r"redis", r"cache", r"broker", r"consumer lag"],
    "Application/Deployment": [r"deploy", r"release", r"rollout", r"\b503\b", r"\b500\b", r"\b502\b", r"\b504\b", r"exception", r"\bbug\b", r"crash", r"error rate", r"http"],
    "Storage": [r"volume", r"\bpv\b", r"\bnfs\b", r"\bs3\b", r"persistentvolume", r"snapshot"],
}

ENV_RULES: list[tuple[str, str]] = [
    (r"\bprod(uction)?\b", "Production"),
    (r"\bstag(e|ing)?\b", "Staging"),
    (r"\bqa\b|\btest(ing)? env", "Test"),
    (r"\bdev(elopment)?\b", "Development"),
]


def analyze(text: str, settings: Any) -> dict[str, Any]:
    """Deterministic extraction -> IncidentAnalysis payload (dict)."""
    low = (text or "").lower()
    # service -----------------------------------------------------------------
    service = None
    for alias, canonical in sorted(SERVICE_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", low):
            service = canonical
            break
    # error -------------------------------------------------------------------
    error = None
    for pattern, label in ERROR_PATTERNS:
        m = re.search(pattern, low)
        if m:
            groups = m.groups()
            err = label
            for gi, g in enumerate(groups, start=0):
                if g and "{0}" in err:
                    err = err.replace("{0}", g.upper() if g.isdigit() else g, 1)
            error = err
            break
    # environment ---------------------------------------------------------------
    environment = "Production"  # incidents reported here are ops incidents
    for pattern, env in ENV_RULES:
        if re.search(pattern, low):
            environment = env
            break
    # event ---------------------------------------------------------------------
    event = None
    for pattern, ev in EVENT_RULES:
        if re.search(pattern, low):
            event = ev
            break
    # severity --------------------------------------------------------------------
    severity = "P2" if environment == "Production" else "P3"
    for pattern, sev in SEVERITY_RULES:
        if re.search(pattern, low):
            severity = sev
            break
    # category ---------------------------------------------------------------------
    scores = {
        cat: sum(1 for p in pats if re.search(p, low)) for cat, pats in CATEGORY_RULES.items()
    }
    best_cat, best_score = max(scores.items(), key=lambda kv: kv[1])
    category = best_cat if best_score > 0 else "General"
    # symptoms / keywords -------------------------------------------------------------
    symptoms = sorted(
        {label for label in [error] if label}
        | {ev for pattern, ev in EVENT_RULES if re.search(pattern, low) and ev == event}
    )
    raw_tokens = content_tokens(text)
    kw: list[str] = []
    seen: set[str] = set()
    for t in raw_tokens:
        lt = t.lower()
        if lt in seen or lt in STOPWORDS or len(lt) < 2:
            continue
        seen.add(lt)
        kw.append(lt)
    if service:
        for t in _TOKEN_RE.findall(service.lower()):
            if t not in seen:
                kw.insert(0, t)
                seen.add(t)
    if error:
        for t in _TOKEN_RE.findall(error.lower()):
            if t not in seen:
                kw.insert(0, t)
                seen.add(t)
    confidence = 0.55 + 0.12 * bool(service) + 0.12 * bool(error) + 0.08 * (category != "General") + 0.05 * bool(event)
    return IncidentAnalysis(
        service=service,
        error=error,
        environment=environment,
        event=event,
        category=category,
        severity=severity,
        symptoms=symptoms or ([error] if error else []),
        keywords=kw[:14],
        confidence=round(min(0.95, confidence), 2),
    ).model_dump()


_LLM_SYSTEM = (
    "You are an incident triage extractor for an SRE knowledge assistant. "
    "From the incident text, return JSON with keys: service, error, environment, event, "
    "category, severity (P0..P4), symptoms (list), keywords (list). "
    "Never invent details not present or strongly implied in the text; use null when unknown. "
    "Allowed categories: Database, Kubernetes / Container, Compute / Resource, Network, "
    "Security / Auth, Middleware, Application/Deployment, Storage, General."
)


def run(state: dict[str, Any]) -> dict[str, Any]:
    settings = settings_of(state)
    text = state["user_input"]
    analysis = analyze(text, settings)

    llm = llm_of(state)
    llm_used = False
    if llm is not None and getattr(llm, "available", False):
        try:
            user = f"Incident text:\n{text[:1500]}\n\nCurrent deterministic extraction (fix only if wrong):\n{json.dumps(analysis)}"
            merged = llm.complete_json(_LLM_SYSTEM, user)
            analysis = _merge_llm(analysis, merged)
            llm_used = True
        except Exception:
            pass  # deterministic result stands

    return {
        "analysis": analysis,
        "llm_used": state.get("llm_used", False) or llm_used,
        "trace": (state.get("trace") or []) + [
            {"node": "incident_analyzer", "status": "ok", "detail": f"service={analysis.get('service')} category={analysis.get('category')} severity={analysis.get('severity')}"}
        ],
    }


_LLM_ALLOWED_KEYS = {"service", "error", "environment", "event", "category", "severity", "symptoms", "keywords"}
_ALLOWED_CATEGORIES = set(CATEGORY_RULES) | {"General"}


def _merge_llm(base: dict[str, Any], merged: dict[str, Any]) -> dict[str, Any]:
    """LLM output may only refine the deterministic pass; values are validated."""
    out = dict(base)
    for k in _LLM_ALLOWED_KEYS:
        v = merged.get(k)
        if v in (None, "", [], {}):
            continue
        if k == "category" and v not in _ALLOWED_CATEGORIES:
            continue
        if k == "severity" and not re.fullmatch(r"P[0-4]", str(v)):
            continue
        if k in {"symptoms", "keywords"} and isinstance(v, list):
            v = [str(x) for x in v if isinstance(x, (str, int, float))][:14]
        elif not isinstance(v, (str, list)):
            continue
        out[k] = v
    out["confidence"] = round(min(0.97, float(merged.get("confidence") or base["confidence"])), 2)
    return out
