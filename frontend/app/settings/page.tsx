"use client";
import { CheckCircle2, KeyRound, ListRestart, Loader2, PlugZap, RefreshCw, Save, ShieldCheck, Trash2, XCircle } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { ErrorBox, Skeleton } from "@/components/ui/misc";
import { Switch } from "@/components/ui/switch";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AnalysisPreferences, ProviderSettings, SettingsView } from "@/types/api";

type Notice = { kind: "ok" | "error"; text: string } | null;

function NoticeLine({ notice }: { notice: Notice }) {
  if (!notice) return null;
  return (
    <p className={cn("flex items-center gap-1.5 text-xs", notice.kind === "ok" ? "text-[var(--success-text)]" : "text-critical")} role="status">
      {notice.kind === "ok" ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />} {notice.text}
    </p>
  );
}

export default function SettingsPage() {
  const settings = useAsync(() => api.settings(), []);
  if (settings.error && !settings.data) return <div className="p-8"><ErrorBox message={settings.error} onRetry={settings.reload} /></div>;
  if (!settings.data) return <div className="space-y-4 p-8"><Skeleton className="h-10 w-64" /><Skeleton className="h-72" /></div>;
  return <SettingsForm s={settings.data} reload={settings.reload} setData={settings.setData} />;
}

function SettingsForm({ s, reload, setData }: { s: SettingsView; reload: () => void; setData: (v: SettingsView) => void }) {
  const [prov, setProv] = useState<ProviderSettings>(s.provider);
  const [prefs, setPrefs] = useState<AnalysisPreferences>(s.analysis);
  const [exclusions, setExclusions] = useState(s.analysis.exclusions.join("\n"));
  const [keyDraft, setKeyDraft] = useState<Record<string, string>>({});
  const [models, setModels] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [provNotice, setProvNotice] = useState<Notice>(null);
  const [keyNotice, setKeyNotice] = useState<Notice>(null);
  const [prefNotice, setPrefNotice] = useState<Notice>(null);
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);
  const info = s.providers[prov.provider];

  async function saveProvider() {
    setBusy("prov");
    setProvNotice(null);
    try {
      const v = await api.saveProvider(prov);
      setData(v);
      setProvNotice({ kind: "ok", text: "Provider settings saved" });
    } catch (e) {
      setProvNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  async function runTest() {
    setBusy("test");
    setTest(null);
    try {
      const r = await api.testProvider({ provider: prov.provider, model: prov.model, base_url: prov.base_url });
      setTest({ ok: r.ok, text: r.ok ? `Connected to ${r.model} in ${r.latency_ms} ms` : r.error || `Unexpected reply: ${r.reply_preview ?? ""}` });
    } catch (e) {
      setTest({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  async function loadModels() {
    setBusy("models");
    try {
      const r = await api.listModels({ provider: prov.provider, base_url: prov.base_url });
      setModels(r.models);
      if (!r.ok) setTest({ ok: false, text: r.error ?? "Could not list models" });
    } finally {
      setBusy(null);
    }
  }

  async function saveKey(p: string) {
    const k = keyDraft[p]?.trim();
    if (!k) return;
    setBusy(`key-${p}`);
    setKeyNotice(null);
    try {
      await api.setKey(p, k);
      setKeyDraft((d) => ({ ...d, [p]: "" }));
      reload();
      setKeyNotice({ kind: "ok", text: `${s.providers[p].label} key stored encrypted on the server` });
    } catch (e) {
      setKeyNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  async function removeKey(p: string) {
    setBusy(`key-${p}`);
    try {
      await api.deleteKey(p);
      reload();
      setKeyNotice({ kind: "ok", text: `${s.providers[p].label} stored key removed` });
    } finally {
      setBusy(null);
    }
  }

  async function savePrefs() {
    setBusy("prefs");
    setPrefNotice(null);
    try {
      const v = await api.saveAnalysis({ ...prefs, exclusions: exclusions.split("\n").map((x) => x.trim()).filter(Boolean) });
      setData(v);
      setPrefNotice({ kind: "ok", text: "Analysis preferences saved" });
    } catch (e) {
      setPrefNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <PageHeader eyebrow="Settings" title="Configuration" description="Provider, credentials and analysis behaviour. Stored server-side in this ContextForge instance." />
      <div className="grid gap-6 px-4 pb-12 sm:px-8 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>AI provider & model</CardTitle>
              <CardDescription>Default provider for new analyses. Can be overridden per upload.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <Field label="Provider" htmlFor="sp">
              <Select id="sp" value={prov.provider} onChange={(e) => { setProv({ ...prov, provider: e.target.value, model: null, base_url: null }); setModels([]); setTest(null); }}>
                {Object.entries(s.providers).map(([k, v]) => (
                  <option key={k} value={k}>{v.label}</option>
                ))}
              </Select>
            </Field>
            {info?.notes ? <p className="text-xs text-muted">{info.notes}</p> : null}
            {prov.provider !== "none" ? (
              <>
                <Field label="Model" htmlFor="sm" hint={info?.default_model ? `Empty = ${info.default_model}` : "Required"}>
                  <div className="flex gap-2">
                    <Input id="sm" list="model-options" value={prov.model ?? ""} onChange={(e) => setProv({ ...prov, model: e.target.value || null })} placeholder={info?.default_model ?? "model-name"} />
                    <datalist id="model-options">
                      {models.map((m) => <option key={m} value={m} />)}
                    </datalist>
                    <Button variant="secondary" onClick={loadModels} disabled={busy === "models"} title="Fetch models available to the configured key">
                      {busy === "models" ? <Loader2 className="animate-spin" /> : <RefreshCw />} List models
                    </Button>
                  </div>
                </Field>
                {models.length ? <p className="text-[11px] text-subtle">{models.length} models available — pick from the model field’s suggestions.</p> : null}
                {info?.needs_base_url || s.allow_provider_base_url_override ? (
                  <Field label="Base URL" htmlFor="sb" hint={info?.needs_base_url ? "Required, e.g. http://localhost:11434/v1" : "Optional override (proxy / gateway)"}>
                    <Input id="sb" value={prov.base_url ?? ""} onChange={(e) => setProv({ ...prov, base_url: e.target.value || null })} placeholder={info?.needs_base_url ? "https://host/v1" : "default"} />
                  </Field>
                ) : null}
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Temperature" htmlFor="st" hint={prov.provider === "anthropic" ? "Not sent: current Claude models reject sampling parameters." : "0–2; low values keep analysis factual."}>
                    <Input id="st" type="number" step="0.1" min={0} max={2} value={prov.temperature} disabled={prov.provider === "anthropic"} onChange={(e) => setProv({ ...prov, temperature: Number(e.target.value) })} />
                  </Field>
                  <Field label="Max output tokens" htmlFor="sx">
                    <Input id="sx" type="number" min={256} max={128000} value={prov.max_output_tokens} onChange={(e) => setProv({ ...prov, max_output_tokens: Number(e.target.value) })} />
                  </Field>
                  <Field label="Request timeout (s)" htmlFor="sto">
                    <Input id="sto" type="number" min={10} max={1800} value={prov.timeout_s} onChange={(e) => setProv({ ...prov, timeout_s: Number(e.target.value) })} />
                  </Field>
                  <Field label="Retries" htmlFor="sr" hint="Exponential backoff; honours Retry-After.">
                    <Input id="sr" type="number" min={0} max={10} value={prov.retries} onChange={(e) => setProv({ ...prov, retries: Number(e.target.value) })} />
                  </Field>
                </div>
              </>
            ) : null}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button onClick={saveProvider} disabled={busy === "prov"}>{busy === "prov" ? <Loader2 className="animate-spin" /> : <Save />} Save provider</Button>
              {prov.provider !== "none" ? (
                <Button variant="secondary" onClick={runTest} disabled={busy === "test"} title="Sends one tiny real request">
                  {busy === "test" ? <Loader2 className="animate-spin" /> : <PlugZap />} Test connection
                </Button>
              ) : null}
            </div>
            <NoticeLine notice={provNotice} />
            {test ? <NoticeLine notice={{ kind: test.ok ? "ok" : "error", text: test.text }} /> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>API keys</CardTitle>
              <CardDescription>Write-only. Keys from environment variables take precedence; stored keys are encrypted at rest (Fernet) and never returned to the browser.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {Object.entries(s.keys).map(([p, k]) => (
              <div key={p} className="rounded-lg border border-border p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 text-sm font-medium"><KeyRound className="size-4 text-subtle" /> {s.providers[p]?.label ?? p}</span>
                  <span className={cn("text-xs font-medium", k.api_key_set ? "text-[var(--success-text)]" : "text-subtle")}>
                    {k.api_key_set ? (k.source === "environment" ? "Set via environment" : "Stored (encrypted)") : "Not set"}
                  </span>
                </div>
                <div className="flex gap-2">
                  <Input type="password" autoComplete="off" value={keyDraft[p] ?? ""} onChange={(e) => setKeyDraft({ ...keyDraft, [p]: e.target.value })} placeholder={k.api_key_set ? "•••••••• (replace)" : "Paste API key"} aria-label={`${p} API key`} disabled={k.source === "environment"} />
                  <Button variant="secondary" onClick={() => saveKey(p)} disabled={!keyDraft[p]?.trim() || busy === `key-${p}`}>Save</Button>
                  {k.source === "stored" ? (
                    <Button variant="ghost" size="icon" onClick={() => removeKey(p)} aria-label={`Remove ${p} key`}><Trash2 /></Button>
                  ) : null}
                </div>
              </div>
            ))}
            <NoticeLine notice={keyNotice} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Analysis preferences</CardTitle>
              <CardDescription>Budgets and limits. Files beyond a budget are listed in the manifest with the reason — never silently dropped.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Default depth" htmlFor="pd">
                <Select id="pd" value={prefs.depth} onChange={(e) => setPrefs({ ...prefs, depth: e.target.value as AnalysisPreferences["depth"] })}>
                  <option value="quick">Quick</option>
                  <option value="standard">Standard</option>
                  <option value="deep">Deep</option>
                </Select>
              </Field>
              <Field label="Token budget per analysis" htmlFor="pb" hint="Input + output tokens across all AI requests.">
                <Input id="pb" type="number" min={5000} step={10000} value={prefs.token_budget} onChange={(e) => setPrefs({ ...prefs, token_budget: Number(e.target.value) })} />
              </Field>
              <Field label="Max file size to parse (KB)" htmlFor="pf">
                <Input id="pf" type="number" min={16} value={prefs.max_file_kb} onChange={(e) => setPrefs({ ...prefs, max_file_kb: Number(e.target.value) })} />
              </Field>
              <Field label="Concurrent AI requests" htmlFor="pc">
                <Input id="pc" type="number" min={1} max={16} value={prefs.max_concurrency} onChange={(e) => setPrefs({ ...prefs, max_concurrency: Number(e.target.value) })} />
              </Field>
            </div>
            <p className="text-[11px] text-subtle">
              Server limits: upload {s.limits.max_upload_mb} MB · extracted {s.limits.max_extracted_mb} MB · {s.limits.max_file_count.toLocaleString()} files · {s.limits.max_single_file_mb} MB per file (set via environment).
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Exclusion rules</CardTitle>
              <CardDescription>One pattern per line. <code className="font-mono">dir/</code> matches a directory anywhere; other patterns are globs on the file name or path.</CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setExclusions(s.default_exclusions.join("\n"))}><ListRestart /> Defaults</Button>
          </CardHeader>
          <CardContent>
            <Textarea value={exclusions} onChange={(e) => setExclusions(e.target.value)} className="min-h-56 font-mono text-xs" aria-label="Exclusion patterns" spellCheck={false} />
          </CardContent>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader>
            <div>
              <CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4 text-primary" /> Privacy</CardTitle>
              <CardDescription>Secrets are always redacted before leaving the server; these controls go further.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="divide-y divide-border">
            <Switch id="ps" checked={prefs.send_source_to_ai} onChange={(v) => setPrefs({ ...prefs, send_source_to_ai: v })} label="Send source excerpts to the AI provider"
              description="When off, only extracted structure (symbols, signatures, routes, models) is sent. Interpretation quality drops, but no source code leaves the server." />
            <Switch id="pca" checked={prefs.cache_ai_responses} onChange={(v) => setPrefs({ ...prefs, cache_ai_responses: v })} label="Cache AI responses"
              description="Re-analysing unchanged files reuses previous model output (keyed by prompt hash). Stored in the server data directory." />
            <Switch id="pk" checked={prefs.keep_uploaded_archive} onChange={(v) => setPrefs({ ...prefs, keep_uploaded_archive: v })} label="Keep uploaded archives"
              description="Off by default: the uploaded ZIP and extracted sources are deleted when the analysis finishes." />
            <div className="flex items-center gap-3 pt-4">
              <Button onClick={savePrefs} disabled={busy === "prefs"}>{busy === "prefs" ? <Loader2 className="animate-spin" /> : <Save />} Save preferences & exclusions</Button>
              <NoticeLine notice={prefNotice} />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
