"""Root-cause taxonomy shared by the Root Cause node and admin analytics."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Taxon:
    label: str
    patterns: list[str] = field(default_factory=list)
    evidence_categories: list[str] = field(
        default_factory=lambda: ["RCA", "POSTMORTEM", "INCIDENT_REPORT", "JIRA_INCIDENT", "RUNBOOK"]
    )

    def matches(self, text: str) -> int:
        hits = 0
        low = text.lower()
        for p in self.patterns:
            if re.search(p, low):
                hits += 1
        return hits


ROOT_CAUSE_TAXONOMY: list[Taxon] = [
    Taxon("Configuration Error", [
        r"config\s*map", r"configmap", r"misconfigur", r"config(uration)? (error|change|drift|value)",
        r"wrong value", r"env(ironment)? variable", r"\bsecret\b.{0,40}(wrong|missing|rotat|expired|invalid)",
        r"\bflag\b.{0,25}(change|toggled|flip)", r"feature flag",
    ]),
    Taxon("Database Failure", [
        r"deadlock", r"replica lag", r"primary failover", r"vacuum", r"long-running (query|transaction)",
        r"connection (pool|limit)", r"pool exhaustion", r"database (timeout|unavailable|down)",
        r"too many connections", r"\bslow quer",
    ]),
    Taxon("Deployment Failure", [
        r"after deployment", r"post-?deploy", r"rollout", r"bad (release|build|image)", r"image pull",
        r"helm (upgrade|release)", r"rollback", r"version (mismatch|bump)", r"\bcicd\b", r"failed migration",
        r"schema migration",
    ]),
    Taxon("Resource Exhaustion", [
        r"\boom\b", r"oomkilled", r"out of memory", r"memory (limit|leak|pressure|exhaustion)",
        r"cpu (throttl|saturat|pressure|pinning)|throttl\w+ cpu|cpu .{0,15}9\d%",
        r"disk (full|utilization|usage|space|pressure)", r"inode", r"file descriptor", r"\belasticity\b",
        r"connection (limit|exhaustion)", r"thread pool",
    ]),
    Taxon("Network Failure", [
        r"packet loss", r"dns (resolution|failure)", r"firewall", r"security group", r"routing",
        r"load balancer", r"network (partition|policy|policies)|netpol", r"latency spike", r"\bmtu\b",
        r"handshake (timeout|failure)",
    ]),
    Taxon("Application Defect", [
        r"null ?pointer", r"\bnpe\b", r"unhandled exception", r"\bbug\b", r"regression", r"memory leak",
        r"infinite loop", r"stack overflow", r"race condition", r"dead code", r"500.{0,30}(exception|stack)",
    ]),
    Taxon("Dependency Failure", [
        r"third[- ]party", r"vendor (api|outage)", r"downstream (service|dependency)", r"upstream (5\d\d|failure)",
        r"\bslb\b", r"external (api|service)", r"dependency (timeout|failure)", r"503", r"service unavailable",
    ]),
    Taxon("Capacity / Scaling Issue", [
        r"traffic spike", r"sudden (surge|increase)", r"autoscal", r"hpa", r"replica count", r"pod capacity",
        r"queue (backlog|depth)", r"kafka lag", r"consumer lag", r"rate limit",
    ]),
    Taxon("Authentication / Access", [
        r"token (expired|invalid|rejected)", r"cert(ificate)? (expired|rotation|renewal)", r"auth(entication)? (failure|error)",
        r"permission denied", r"access denied", r"\bsso\b", r"ldap", r"unauthorized", r"forbidden",
    ]),
    Taxon("Cache / Middleware Failure", [
        r"redis", r"memcached", r"cache (eviction|miss|stampede)", r"rabbitmq", r"\bkafka\b", r"queue full",
        r"broker", r"elasticsearch",
    ]),
]


def classify_text(text: str) -> tuple[str, int]:
    """Return (label, hits) for the strongest taxonomy match (Other when none)."""
    best, best_hits = "Other", 0
    for taxon in ROOT_CAUSE_TAXONOMY:
        h = taxon.matches(text)
        if h > best_hits:
            best, best_hits = taxon.label, h
    return best, best_hits


TAXON_LABELS = [t.label for t in ROOT_CAUSE_TAXONOMY]
