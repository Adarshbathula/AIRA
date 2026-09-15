import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { chatApi, incidentApi, apiError } from "../services/api";
import type { AIResponse, ChatMessage, Conversation } from "../types";
import AssistantResponse from "../components/AssistantResponse";
import { Badge, Spinner } from "../components/ui";
import { useToast } from "../hooks/useToast";
import { relTime } from "../utils/format";

const EXAMPLES = [
  "Payment API returns HTTP 503 after deployment.",
  "Database connection timeout in Order Service.",
  "Payment pods are repeatedly entering CrashLoopBackOff.",
  "Production server CPU utilization has exceeded 95%.",
  "Application pods are being terminated because of OOMKilled.",
  "Users cannot log in after the latest deployment.",
];

type Item = { kind: "user"; text: string; at: string } | { kind: "assistant"; msg: ChatMessage; ai?: AIResponse };

export default function Assistant() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [convId, setConvId] = useState<number | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [thinkingStep, setThinkingStep] = useState("");
  const [followUp, setFollowUp] = useState(false);
  const toast = useToast();
  const bottomRef = useRef<HTMLDivElement>(null);
  const aiCache = useRef<Map<number, AIResponse>>(new Map());

  const refreshConversations = useCallback(async () => {
    try { setConversations(await chatApi.list()); } catch { /* non-fatal */ }
  }, []);

  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinked = useRef(false);

  useEffect(() => { void refreshConversations(); }, [refreshConversations]);

  // deep link support: /assistant?c=<conversation id> opens that history thread
  useEffect(() => {
    if (deepLinked.current) return;
    const c = searchParams.get("c");
    if (c && /^\d+$/.test(c)) {
      deepLinked.current = true;
      void loadConversation(Number(c));
      setSearchParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [items, busy, thinkingStep]);

  const loadConversation = async (id: number) => {
    setConvId(id);
    setItems([]);
    try {
      const detail = await chatApi.detail(id);
      const out: Item[] = [];
      for (const m of detail.messages) {
        if (m.role === "user") out.push({ kind: "user", text: m.content, at: m.created_at });
        else if (m.role === "assistant") out.push({ kind: "assistant", msg: m });
      }
      setItems(out);
      const ids = out.filter((i) => i.kind === "assistant").map((i) => (i as Extract<Item, { kind: "assistant" }>).msg.incident_id).filter(Boolean) as number[];
      await Promise.all(ids.map(async (iid) => {
        if (aiCache.current.has(iid)) return;
        try { aiCache.current.set(iid, await incidentApi.detail(iid)); } catch { /* keep raw text only */ }
      }));
      setItems([...out]);
    } catch (e) {
      toast.error(apiError(e, "Could not open conversation"));
    }
  };

  const newChat = () => { setConvId(null); setItems([]); setFollowUp(false); };

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || busy) return;
    if (!convId) setFollowUp(false);
    setItems((prev) => [...prev, { kind: "user", text: message, at: new Date().toISOString() }]);
    setInput("");
    setBusy(true);
    setThinkingStep("Analyzing incident…");
    const stages = ["Building retrieval query…", "Searching enterprise knowledge…", "Grading context…", "Rewriting query (self-heal)…", "Matching historical incidents…", "Validating evidence…"];
    let s = 0;
    const ticker = window.setInterval(() => { s = (s + 1) % stages.length; setThinkingStep(s === 1 ? "Analyzing incident…" : stages[s]); }, 1400);
    try {
      const res = await chatApi.send(message, convId, followUp);
      window.clearInterval(ticker);
      aiCache.current.set(res.ai.incident_id, res.ai);
      setItems((prev) => [...prev, { kind: "assistant", msg: res.assistant_message, ai: res.ai }]);
      setConvId(res.conversation_id);
      setFollowUp(true);
      void refreshConversations();
      if (res.ai.insufficient_evidence) toast.info("Insufficient evidence: escalate to an SRE — nothing was invented.");
    } catch (e) {
      window.clearInterval(ticker);
      toast.error(apiError(e, "Analysis failed"));
      setItems((prev) => [
        ...prev,
        {
          kind: "assistant",
          msg: {
            id: -Date.now(), role: "assistant", incident_id: null, created_at: new Date().toISOString(),
            content: `⚠ ${apiError(e, "The analysis could not be completed.")}`,
          },
        },
      ]);
    } finally {
      setBusy(false);
      setThinkingStep("");
    }
  };

  return (
    <div className="-m-4 grid h-[calc(100vh-4rem)] sm:-m-6 lg:grid-cols-[300px_minmax(0,1fr)]">
      {/* conversation rail */}
      <aside className="hidden min-h-0 flex-col border-r border-slate-200 dark:border-white/10 bg-white dark:bg-[#262626] lg:flex">
        <div className="border-b border-slate-100 dark:border-white/5 p-3">
          <button className="btn-primary w-full justify-center" onClick={newChat}>+ New Incident</button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <p className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">Recent analyses</p>
          {conversations.length === 0 && <p className="px-2 py-3 text-xs text-slate-500 dark:text-slate-400">No conversations yet.</p>}
          <ul className="space-y-0.5">
            {conversations.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => void loadConversation(c.id)}
                  className={`w-full rounded-lg px-2.5 py-2 text-left text-sm leading-snug hover:bg-slate-100 hover:dark:bg-[#2a2a2a] ${convId === c.id ? "bg-brand-50 ring-1 ring-brand-100" : ""}`}
                >
                  <span className="line-clamp-2 font-medium text-slate-700 dark:text-slate-300">{c.title}</span>
                  <span className="mt-0.5 flex items-center gap-2 text-[10px] text-slate-400 dark:text-slate-500">
                    {relTime(c.updated_at)} · {c.incident_count} incident{c.incident_count === 1 ? "" : "s"}
                    {c.last_incident && <Badge tone="bg-slate-100 dark:bg-[#212121] text-slate-500 dark:text-slate-400">{Math.round(c.last_incident.confidence_score * 100)}%</Badge>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </aside>

      {/* chat column */}
      <section className="flex min-h-0 min-w-0 flex-col bg-slate-50 dark:bg-[#171717]">
        <div className="flex items-center gap-3 border-b border-slate-200 dark:border-white/10 bg-white/90 dark:bg-[#171717]/90 px-4 py-3 backdrop-blur">
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-200">Incident Resolution Assistant</h2>
          {convId && (
            <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
              <input type="checkbox" className="accent-brand-600" checked={followUp} onChange={(e) => setFollowUp(e.target.checked)} />
              follow-up on same incident
            </label>
          )}
          <span className={`ml-auto text-[11px] ${followUp ? "" : "text-slate-400 dark:text-slate-500"}`}>{convId ? `conversation #${convId}` : "new conversation"}</span>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-5 sm:px-6">
          {items.length === 0 && !busy && (
            <div className="mx-auto max-w-2xl pt-8 text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-ink-950 text-lg font-bold text-white">AI</div>
              <h3 className="mt-3 text-base font-semibold text-slate-800 dark:text-slate-200">Describe a production incident</h3>
              <p className="mx-auto mt-1 max-w-lg text-sm text-slate-500 dark:text-slate-400">
                The assistant analyses it, retrieves relevant SOPs / runbooks / RCAs / past incidents, grades
                the evidence, retries weak retrieval, then recommends only what the knowledge base supports.
              </p>
              <div className="mx-auto mt-5 grid max-w-xl grid-cols-1 gap-2 sm:grid-cols-2">
                {EXAMPLES.map((ex) => (
                  <button key={ex} onClick={() => void send(ex)} className="rounded-lg border border-slate-200 dark:border-white/10 bg-white dark:bg-[#262626] px-3 py-2 text-left text-xs text-slate-600 dark:text-slate-300 hover:border-brand-400 hover:text-brand-600">
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          )}

          {items.map((it, idx) =>
            it.kind === "user" ? (
              <div key={idx} className="ml-auto max-w-[85%] rounded-2xl rounded-tr-sm bg-brand-600 px-4 py-2.5 text-sm text-white shadow-sm dark:shadow-none">
                <p className="whitespace-pre-wrap">{it.text}</p>
                <p className="mt-1 text-right text-[10px] text-white/70">{relTime(it.at)}</p>
              </div>
            ) : (
              <div key={idx} className="mr-auto w-full max-w-[96%] rounded-2xl rounded-tl-sm border border-slate-200 dark:border-white/10 bg-white dark:bg-[#262626] p-4 shadow-sm dark:shadow-none">
                <div className="mb-2 flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-md bg-ink-950 text-[10px] font-bold text-white">AI</span>
                  <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">Incident Assistant</span>
                  {it.ai && (
                    <span className="ml-auto text-[10px] text-slate-400 dark:text-slate-500">
                      {it.ai.retrieval_attempts} retrieval attempt{it.ai.retrieval_attempts > 1 ? "s" : ""} ·{" "}
                      {it.ai.supporting_document_count} doc{it.ai.supporting_document_count === 1 ? "" : "s"}
                    </span>
                  )}
                </div>
                {it.ai ? (
                  <AssistantResponse ai={it.ai} />
                ) : (
                  <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-700 dark:text-slate-300">{it.msg.content}</pre>
                )}
              </div>
            ),
          )}

          {busy && (
            <div className="mr-auto flex max-w-[92%] items-center gap-3 rounded-2xl rounded-tl-sm border border-slate-200 dark:border-white/10 bg-white dark:bg-[#262626] px-4 py-3 text-sm text-slate-600 dark:text-slate-300 shadow-sm dark:shadow-none">
              <Spinner className="h-4 w-4 text-brand-600 dark:text-brand-400" />
              <span>{thinkingStep}</span>
              <span className="flex gap-1 text-slate-300">
                <i className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-300 dark:bg-slate-500" />
                <i className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-300 dark:bg-slate-500 [animation-delay:150ms]" />
                <i className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-300 dark:bg-slate-500 [animation-delay:300ms]" />
              </span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-slate-200 dark:border-white/10 bg-white dark:bg-[#262626] p-3 sm:p-4">
          <form
            className="mx-auto flex max-w-4xl items-end gap-2"
            onSubmit={(e) => { e.preventDefault(); void send(input); }}
          >
            <textarea
              className="input max-h-40 min-h-[46px] resize-y py-2.5"
              rows={1}
              placeholder="Describe your production incident… e.g. Checkout API throwing HTTP 500 after last deploy"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }}
              disabled={busy}
            />
            <button className="btn-primary h-[46px] shrink-0" disabled={busy || input.trim().length < 4} type="submit">
              {busy ? <Spinner /> : "Send"}
            </button>
          </form>
          <p className="mx-auto mt-1.5 max-w-4xl text-[10px] text-slate-400 dark:text-slate-500">
            Enter to send · Shift+Enter for a newline. Answers are grounded in retrieved evidence; if evidence is
            insufficient the assistant says so instead of guessing.
          </p>
        </div>
      </section>
    </div>
  );
}
