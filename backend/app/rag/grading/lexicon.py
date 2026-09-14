"""Shared enterprise-ops lexicon used by the analyzer and the query rewriter."""
from __future__ import annotations

import re

DOMAIN_SYNONYMS: dict[str, list[str]] = {
    "503": ["service unavailable", "load balancer", "no healthy upstream", "readiness", "liveness"],
    "500": ["internal server error", "exception", "stack trace"],
    "502": ["bad gateway", "upstream", "connection reset"],
    "504": ["gateway timeout", "upstream timeout", "latency"],
    "401": ["authentication", "unauthorized", "token invalid", "session"],
    "403": ["forbidden", "authorization", "permissions", "rbac"],
    "timeout": ["latency", "connection refused", "deadline exceeded", "unreachable"],
    "oomkilled": ["out of memory", "memory limit", "heap", "container", "eviction"],
    "memory": ["heap", "ram", "leak", "limit range"],
    "cpu": ["cpu saturation", "throttling", "load average", "steal"],
    "disk": ["disk full", "inode", "volume", "filesystem", "pv"],
    "crashloopbackoff": ["pod restart", "image pull", "probe failed", "init container", "exit code"],
    "restart": ["crash", "exit code", "liveness probe", "oom"],
    "pod": ["kubernetes", "kubectl", "container", "kubelet", "node"],
    "kubernetes": ["k8s", "kubectl", "namespace", "deployment", "daemonset"],
    "configmap": ["environment variable", "secret", "config", "env", "property"],
    "secret": ["credentials", "rotation", "configmap", "env"],
    "database": ["postgres", "mysql", "connection pool", "query", "replica", "primary"],
    "migration": ["schema", "flyway", "liquibase", "ddl", "lock"],
    "connection pool": ["pool exhaustion", "max connections", "idle timeout"],
    "deployment": ["rollout", "helm", "release", "rollback", "image tag", "canary"],
    "rollback": ["redeploy", "previous version", "release"],
    "certificate": ["tls", "expired", "ssl", "handshake"],
    "dns": ["resolver", "svc.cluster.local", "nameserver"],
    "cache": ["redis", "eviction", "ttl", "miss ratio"],
    "queue": ["kafka", "rabbitmq", "lag", "consumer", "partition"],
    "latency": ["p99", "slow queries", "jvm gc", "garbage collection"],
    "login": ["sso", "oauth", "token", "session", "idp"],
    "auth": ["oauth", "token", "jwt", "sso", "credentials"],
    "network": ["firewall", "security group", "routing", "packet loss", "mtu"],
}

STOPWORDS = set(
    """a an the and or but if then this that these those is are was were be been being of in on at to for
    with from by as it its we our us you your they them their he she do does did doing have has had not no
    after before during while when where which who whom how why what all any some more most very just also
    new now currently today yesterday since until per via into out up down over under again once upon may
    might must can could should would will shall need needs appear appears appearing seem seems seems
    also still already just quite rather unable establish repeatedly entering currently""".split()
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+#/-]*")


def expand_tokens(tokens: list[str], max_additions: int = 12) -> list[str]:
    """Add canonical synonyms for known domain tokens (deduped, order stable)."""
    out: list[str] = []
    seen = {t.lower() for t in tokens}
    for tok in tokens:
        for syn in DOMAIN_SYNONYMS.get(tok.lower(), []):
            for w in [syn] + _TOKEN_RE.findall(syn):
                lw = w.lower()
                if lw not in seen and lw not in STOPWORDS:
                    seen.add(lw)
                    out.append(w)
    return out[:max_additions]


_TRAIL_PUNCT = re.compile(r"[._,;:!?'\"()\[\]{}]+$")


def content_tokens(text: str, remove_stop: bool = True) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in _TOKEN_RE.findall(text or ""):
        t = _TRAIL_PUNCT.sub("", t).strip("-")
        lt = t.lower()
        if len(lt) < 2 or lt in seen:
            continue
        if remove_stop and lt in STOPWORDS:
            continue
        seen.add(lt)
        out.append(t)
    return out
