"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiRequestError,
  clearAdminAuthCredential,
  createQmsAudit,
  createQmsCapa,
  createQmsChange,
  createQmsKpiSnapshot,
  createQmsManagementReview,
  createQmsRelease,
  createQmsRisk,
  createQmsSupplier,
  exportQmsReport,
  getQmsAudits,
  getQmsCapa,
  getQmsChanges,
  getQmsDashboard,
  getQmsEvidence,
  getQmsManagementReviews,
  getQmsReleases,
  getQmsRisks,
  getQmsSuppliers,
  saveAdminAuthCredential,
  scanQmsRuntime,
  updateQmsAudit,
  updateQmsCapa,
  updateQmsChange,
  updateQmsManagementReview,
  updateQmsRelease,
  updateQmsRisk,
  updateQmsSupplier,
} from "@/lib/api";
import type {
  QmsAuditRead,
  QmsCapaRead,
  QmsChangeRead,
  QmsDashboardRead,
  QmsEvidenceRead,
  QmsManagementReviewRead,
  QmsReleaseRead,
  QmsRiskRead,
  QmsSupplierRead,
} from "@/lib/types";

type TabKey = "phase1" | "phase2" | "phase3" | "phase4";

type FormState = Record<string, string>;

const tabs: Array<{ key: TabKey; label: string; description: string }> = [
  { key: "phase1", label: "문서화·KPI", description: "QMS 문서, KPI, 런타임 증적 상태" },
  { key: "phase2", label: "Risk·CAPA", description: "리스크 등록부와 시정·예방조치" },
  { key: "phase3", label: "Change·Release·Supplier", description: "변경관리, 릴리즈 증적, 공급자 통제" },
  { key: "phase4", label: "Audit·Review·Evidence", description: "내부심사, 경영검토, 인증 증적" },
];

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
}

function number(value: number | undefined | null) {
  return new Intl.NumberFormat("ko-KR").format(value ?? 0);
}

function statusClass(status?: string | null) {
  const value = String(status || "").toLowerCase();
  if (["closed", "completed", "released", "accepted", "active", "captured", "indexed"].includes(value)) return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (["open", "planned", "draft", "pending", "running"].includes(value)) return "border-amber-200 bg-amber-50 text-amber-700";
  if (["failed", "blocked", "overdue", "rejected"].includes(value)) return "border-rose-200 bg-rose-50 text-rose-700";
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function Field({ label, value, onChange, placeholder, textarea = false }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; textarea?: boolean }) {
  return (
    <div className="space-y-2">
      <Label className="text-xs font-semibold text-slate-600">{label}</Label>
      {textarea ? (
        <Textarea value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="min-h-[76px]" />
      ) : (
        <Input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
      )}
    </div>
  );
}

function MetricCard({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl">{value}</CardTitle>
      </CardHeader>
      {note ? <CardContent className="text-xs text-slate-500">{note}</CardContent> : null}
    </Card>
  );
}

function SummaryCard({ title, summary }: { title: string; summary: { total: number; open: number; overdue: number; closed: number } }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardDescription>{title}</CardDescription>
        <CardTitle>{number(summary.total)}건</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-3 gap-2 text-xs">
        <span className="rounded-lg bg-amber-50 px-2 py-1 text-amber-700">Open {number(summary.open)}</span>
        <span className="rounded-lg bg-rose-50 px-2 py-1 text-rose-700">Overdue {number(summary.overdue)}</span>
        <span className="rounded-lg bg-emerald-50 px-2 py-1 text-emerald-700">Closed {number(summary.closed)}</span>
      </CardContent>
    </Card>
  );
}

function isAdminAuthError(error: unknown) {
  return error instanceof ApiRequestError && error.status === 401;
}

function formatQmsError(error: unknown, fallback: string) {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "관리자 인증이 필요합니다. 설정된 관리자 계정으로 로그인한 뒤 다시 시도하세요.";
    }
    if (error.status === 503 && error.detail === "admin_auth_not_configured") {
      return "관리자 인증이 켜져 있지만 관리자 계정 또는 비밀번호가 설정되지 않았습니다.";
    }
    return error.message;
  }
  return error instanceof Error ? error.message : fallback;
}

export function QmsWorkspace({ initialDashboard }: { initialDashboard: QmsDashboardRead | null }) {
  const [activeTab, setActiveTab] = useState<TabKey>("phase1");
  const [dashboard, setDashboard] = useState<QmsDashboardRead | null>(initialDashboard);
  const [risks, setRisks] = useState<QmsRiskRead[]>([]);
  const [capa, setCapa] = useState<QmsCapaRead[]>([]);
  const [changes, setChanges] = useState<QmsChangeRead[]>([]);
  const [releases, setReleases] = useState<QmsReleaseRead[]>([]);
  const [suppliers, setSuppliers] = useState<QmsSupplierRead[]>([]);
  const [audits, setAudits] = useState<QmsAuditRead[]>([]);
  const [reviews, setReviews] = useState<QmsManagementReviewRead[]>([]);
  const [evidence, setEvidence] = useState<QmsEvidenceRead[]>(initialDashboard?.recent_evidence ?? []);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [authForm, setAuthForm] = useState<FormState>({ username: "", password: "" });
  const [riskForm, setRiskForm] = useState<FormState>({ title: "", mitigation_plan: "", owner: "" });
  const [capaForm, setCapaForm] = useState<FormState>({ title: "", problem_statement: "", root_cause: "", owner: "" });
  const [changeForm, setChangeForm] = useState<FormState>({ title: "", impact_summary: "", rollback_plan: "" });
  const [releaseForm, setReleaseForm] = useState<FormState>({ title: "", branch: "main", commit_hash: "", test_summary: "" });
  const [supplierForm, setSupplierForm] = useState<FormState>({ name: "", service_scope: "", owner: "operations" });
  const [auditForm, setAuditForm] = useState<FormState>({ title: "", scope: "", auditor: "" });
  const [reviewForm, setReviewForm] = useState<FormState>({ title: "", chair: "", inputs_summary: "" });

  async function reloadAll() {
    setBusy("reload");
    try {
      const [nextDashboard, nextRisks, nextCapa, nextChanges, nextReleases, nextSuppliers, nextAudits, nextReviews, nextEvidence] = await Promise.all([
        getQmsDashboard(),
        getQmsRisks(),
        getQmsCapa(),
        getQmsChanges(),
        getQmsReleases(),
        getQmsSuppliers(),
        getQmsAudits(),
        getQmsManagementReviews(),
        getQmsEvidence(),
      ]);
      setDashboard(nextDashboard);
      setRisks(nextRisks);
      setCapa(nextCapa);
      setChanges(nextChanges);
      setReleases(nextReleases);
      setSuppliers(nextSuppliers);
      setAudits(nextAudits);
      setReviews(nextReviews);
      setEvidence(nextEvidence);
      setAuthRequired(false);
      setMessage("QMS 데이터를 새로고침했습니다.");
    } catch (error) {
      if (isAdminAuthError(error)) {
        setAuthRequired(true);
      }
      setMessage(formatQmsError(error, "QMS 새로고침 실패"));
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    void reloadAll();
  }, []);

  async function runAction(name: string, action: () => Promise<unknown>, success: string) {
    setBusy(name);
    try {
      await action();
      setMessage(success);
      await reloadAll();
    } catch (error) {
      if (isAdminAuthError(error)) {
        setAuthRequired(true);
      }
      setMessage(formatQmsError(error, `${name} failed`));
    } finally {
      setBusy(null);
    }
  }

  async function submitAdminAuth() {
    const username = authForm.username.trim();
    const password = authForm.password;
    if (!username || !password) {
      setMessage("관리자 계정과 비밀번호를 입력하세요.");
      return;
    }
    saveAdminAuthCredential(username, password);
    setAuthRequired(false);
    setMessage("관리자 인증 정보를 세션에 저장했습니다.");
    await reloadAll();
  }

  async function resetAdminAuth() {
    clearAdminAuthCredential();
    setAuthRequired(true);
    setMessage("저장된 관리자 인증 정보를 지웠습니다.");
  }

  const kpi = dashboard?.current_kpi;
  const runtime = dashboard?.runtime_summary ?? {};
  const qualityPassRate = useMemo(() => {
    if (!kpi?.published_total) return "0%";
    return `${Math.round((kpi.quality_gate_pass_count / kpi.published_total) * 100)}%`;
  }, [kpi]);

  return (
    <div className="space-y-5">
      <Card className="overflow-hidden border-slate-200 bg-slate-950 text-white">
        <CardHeader className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <CardDescription className="text-slate-300">ISO 9001 Quality Management System</CardDescription>
              <CardTitle className="mt-2 flex items-center gap-3 text-3xl">
                <ShieldCheck className="h-8 w-8 text-sky-300" /> BloggerGent QMS 대시보드
              </CardTitle>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
                게시 품질 KPI, 리스크, CAPA, 변경·릴리즈 증적, 공급자 통제, 내부심사와 경영검토를 하나의 운영 탭에서 관리합니다.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={reloadAll} disabled={!!busy}>
                <RefreshCw className="mr-2 h-4 w-4" /> 새로고침
              </Button>
              <Button variant="outline" onClick={() => runAction("snapshot", () => createQmsKpiSnapshot(), "KPI 스냅샷을 저장했습니다.")} disabled={!!busy}>
                KPI 스냅샷
              </Button>
              <Button variant="outline" onClick={() => runAction("scan", () => scanQmsRuntime(500), "런타임 증적 스캔을 완료했습니다.")} disabled={!!busy}>
                런타임 스캔
              </Button>
              <Button variant="outline" onClick={() => runAction("export", () => exportQmsReport(), "QMS 리포트를 export했습니다.")} disabled={!!busy}>
                리포트 Export
              </Button>
            </div>
          </div>
          {message ? <div className="rounded-xl border border-white/10 bg-white/10 px-4 py-3 text-sm text-slate-100">{message}</div> : null}
        </CardHeader>
      </Card>

      {authRequired ? (
        <Card className="border-amber-200 bg-amber-50">
          <CardHeader>
            <CardTitle>관리자 인증</CardTitle>
            <CardDescription>QMS API는 조회를 포함해 모두 관리자 인증 대상입니다. 입력값은 현재 브라우저 세션에만 저장됩니다.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-[1fr_1fr_auto_auto] md:items-end">
            <Field label="관리자 계정" value={authForm.username} onChange={(value) => setAuthForm((current) => ({ ...current, username: value }))} placeholder="admin" />
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-slate-600">관리자 비밀번호</Label>
              <Input
                type="password"
                value={authForm.password}
                onChange={(event) => setAuthForm((current) => ({ ...current, password: event.target.value }))}
                placeholder="설정된 관리자 비밀번호"
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    void submitAdminAuth();
                  }
                }}
              />
            </div>
            <Button onClick={() => void submitAdminAuth()} disabled={busy === "reload"}>인증 후 새로고침</Button>
            <Button variant="outline" onClick={() => void resetAdminAuth()}>세션 삭제</Button>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="LIVE published URL" value={number(kpi?.published_total)} note="live는 published로 정규화" />
        <MetricCard label="품질 게이트 Pass" value={qualityPassRate} note={`${number(kpi?.quality_gate_pass_count)} / ${number(kpi?.published_total)}`} />
        <MetricCard label="색인됨 / 미색인 / Unknown" value={`${number(kpi?.indexed_count)} / ${number(kpi?.not_indexed_count)} / ${number(kpi?.unknown_index_count)}`} />
        <MetricCard label="런타임 증적" value={number(runtime.evidence_count)} note={runtime.latest_scan_status || "missing"} />
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <SummaryCard title="Risk" summary={dashboard?.risk_summary ?? { total: 0, open: 0, overdue: 0, closed: 0 }} />
        <SummaryCard title="CAPA" summary={dashboard?.capa_summary ?? { total: 0, open: 0, overdue: 0, closed: 0 }} />
        <SummaryCard title="Change/Release" summary={dashboard?.change_summary ?? { total: 0, open: 0, overdue: 0, closed: 0 }} />
        <SummaryCard title="Audit/Review" summary={dashboard?.audit_summary ?? { total: 0, open: 0, overdue: 0, closed: 0 }} />
      </div>

      <div className="grid gap-2 lg:grid-cols-4">
        {tabs.map((tab) => (
          <button key={tab.key} onClick={() => setActiveTab(tab.key)} className={`rounded-2xl border px-4 py-3 text-left transition ${activeTab === tab.key ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white text-slate-800 hover:bg-slate-50"}`}>
            <p className="text-sm font-semibold">{tab.label}</p>
            <p className={`mt-1 text-xs ${activeTab === tab.key ? "text-slate-300" : "text-slate-500"}`}>{tab.description}</p>
          </button>
        ))}
      </div>

      {activeTab === "phase1" ? <PhaseOne dashboard={dashboard} evidence={evidence} /> : null}
      {activeTab === "phase2" ? (
        <PhaseTwo
          risks={risks}
          capa={capa}
          riskForm={riskForm}
          setRiskForm={setRiskForm}
          capaForm={capaForm}
          setCapaForm={setCapaForm}
          runAction={runAction}
        />
      ) : null}
      {activeTab === "phase3" ? (
        <PhaseThree
          changes={changes}
          releases={releases}
          suppliers={suppliers}
          changeForm={changeForm}
          setChangeForm={setChangeForm}
          releaseForm={releaseForm}
          setReleaseForm={setReleaseForm}
          supplierForm={supplierForm}
          setSupplierForm={setSupplierForm}
          runAction={runAction}
        />
      ) : null}
      {activeTab === "phase4" ? (
        <PhaseFour
          audits={audits}
          reviews={reviews}
          evidence={evidence}
          auditForm={auditForm}
          setAuditForm={setAuditForm}
          reviewForm={reviewForm}
          setReviewForm={setReviewForm}
          runAction={runAction}
        />
      ) : null}
    </div>
  );
}

function PhaseOne({ dashboard, evidence }: { dashboard: QmsDashboardRead | null; evidence: QmsEvidenceRead[] }) {
  const kpi = dashboard?.current_kpi;
  return (
    <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <Card>
        <CardHeader>
          <CardTitle>품질 KPI 커버리지</CardTitle>
          <CardDescription>published URL 기준 SEO/GEO/CTR/Lighthouse/색인 커버리지입니다.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader><TableRow><TableHead>항목</TableHead><TableHead>반영</TableHead><TableHead>누락</TableHead><TableHead>커버리지</TableHead></TableRow></TableHeader>
            <TableBody>
              {(kpi?.coverage ?? []).map((item) => (
                <TableRow key={item.name}><TableCell>{item.label}</TableCell><TableCell>{number(item.covered)} / {number(item.total)}</TableCell><TableCell>{number(item.missing)}</TableCell><TableCell>{item.coverage_percent}%</TableCell></TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>QMS 문서 상태</CardTitle>
          <CardDescription>repo 문서와 runtime 증적을 연결하는 기준 문서입니다.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {(dashboard?.documents ?? []).map((doc) => (
            <div key={doc.document_key} className="rounded-xl border border-slate-200 p-3">
              <div className="flex items-start justify-between gap-3"><p className="font-semibold text-slate-900">{doc.title}</p><Badge className={statusClass(doc.status)}>{doc.status}</Badge></div>
              <p className="mt-1 text-xs text-slate-500">{doc.phase} · {doc.clause || "clause 미지정"}</p>
              <p className="mt-1 break-all text-xs text-slate-500">{doc.source_path || "문서 경로 없음"}</p>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card className="xl:col-span-2">
        <CardHeader>
          <CardTitle>최근 증적</CardTitle>
          <CardDescription>런타임 스캔과 QMS 리포트 export로 수집된 evidence item입니다.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader><TableRow><TableHead>유형</TableHead><TableHead>제목</TableHead><TableHead>상태</TableHead><TableHead>수집일</TableHead><TableHead>경로</TableHead></TableRow></TableHeader>
            <TableBody>
              {evidence.map((item) => <TableRow key={item.id}><TableCell>{item.evidence_type}</TableCell><TableCell>{item.title}</TableCell><TableCell><Badge className={statusClass(item.status)}>{item.status}</Badge></TableCell><TableCell>{formatDate(item.captured_at)}</TableCell><TableCell className="max-w-[460px] truncate">{item.runtime_path || item.source_path || "-"}</TableCell></TableRow>)}
              {evidence.length === 0 ? <TableRow><TableCell colSpan={5} className="text-sm text-slate-500">아직 수집된 QMS 증적이 없습니다.</TableCell></TableRow> : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function PhaseTwo({ risks, capa, riskForm, setRiskForm, capaForm, setCapaForm, runAction }: any) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Risk Register</CardTitle><CardDescription>RPN 기준으로 리스크를 등록하고 종료합니다.</CardDescription></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Field label="리스크 제목" value={riskForm.title} onChange={(v) => setRiskForm({ ...riskForm, title: v })} placeholder="예: 색인 unknown 과다" />
            <Field label="담당자" value={riskForm.owner} onChange={(v) => setRiskForm({ ...riskForm, owner: v })} placeholder="operations" />
            <Field label="완화 계획" value={riskForm.mitigation_plan} onChange={(v) => setRiskForm({ ...riskForm, mitigation_plan: v })} placeholder="측정/동기화 보정" />
          </div>
          <Button onClick={() => runAction("create-risk", () => createQmsRisk({ ...riskForm, title: riskForm.title || "운영 리스크", severity: 3, occurrence: 3, detection: 3 }), "리스크를 등록했습니다.")}>리스크 등록</Button>
          <Table><TableHeader><TableRow><TableHead>RPN</TableHead><TableHead>제목</TableHead><TableHead>상태</TableHead><TableHead>담당</TableHead><TableHead /></TableRow></TableHeader><TableBody>
            {risks.map((item: QmsRiskRead) => <TableRow key={item.id}><TableCell>{item.rpn}</TableCell><TableCell>{item.title}</TableCell><TableCell><Badge className={statusClass(item.status)}>{item.status}</Badge></TableCell><TableCell>{item.owner || "-"}</TableCell><TableCell><Button size="sm" variant="outline" onClick={() => runAction("close-risk", () => updateQmsRisk(item.id, { status: "closed", closed_at: new Date().toISOString() }), "리스크를 종료했습니다.")}>종료</Button></TableCell></TableRow>)}
          </TableBody></Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>CAPA</CardTitle><CardDescription>문제, 원인, 시정·예방조치와 효과성을 추적합니다.</CardDescription></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="CAPA 제목" value={capaForm.title} onChange={(v) => setCapaForm({ ...capaForm, title: v })} />
            <Field label="담당자" value={capaForm.owner} onChange={(v) => setCapaForm({ ...capaForm, owner: v })} />
            <Field label="문제 진술" value={capaForm.problem_statement} onChange={(v) => setCapaForm({ ...capaForm, problem_statement: v })} textarea />
            <Field label="근본 원인" value={capaForm.root_cause} onChange={(v) => setCapaForm({ ...capaForm, root_cause: v })} textarea />
          </div>
          <Button onClick={() => runAction("create-capa", () => createQmsCapa({ ...capaForm, title: capaForm.title || "CAPA case", problem_statement: capaForm.problem_statement || "문제 진술 필요" }), "CAPA를 등록했습니다.")}>CAPA 등록</Button>
          <Table><TableHeader><TableRow><TableHead>제목</TableHead><TableHead>상태</TableHead><TableHead>우선순위</TableHead><TableHead /></TableRow></TableHeader><TableBody>
            {capa.map((item: QmsCapaRead) => <TableRow key={item.id}><TableCell>{item.title}</TableCell><TableCell><Badge className={statusClass(item.status)}>{item.status}</Badge></TableCell><TableCell>{item.priority}</TableCell><TableCell><Button size="sm" variant="outline" onClick={() => runAction("verify-capa", () => updateQmsCapa(item.id, { status: "completed", verified_at: new Date().toISOString(), effectiveness_score: 80 }), "CAPA를 검증 완료했습니다.")}>검증완료</Button></TableCell></TableRow>)}
          </TableBody></Table>
        </CardContent>
      </Card>
    </div>
  );
}

function PhaseThree({ changes, releases, suppliers, changeForm, setChangeForm, releaseForm, setReleaseForm, supplierForm, setSupplierForm, runAction }: any) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-3">
        <Card><CardHeader><CardTitle>Change Control</CardTitle><CardDescription>변경 영향과 rollback을 기록합니다.</CardDescription></CardHeader><CardContent className="space-y-3">
          <Field label="변경 제목" value={changeForm.title} onChange={(v) => setChangeForm({ ...changeForm, title: v })} />
          <Field label="영향 요약" value={changeForm.impact_summary} onChange={(v) => setChangeForm({ ...changeForm, impact_summary: v })} textarea />
          <Field label="Rollback 계획" value={changeForm.rollback_plan} onChange={(v) => setChangeForm({ ...changeForm, rollback_plan: v })} textarea />
          <Button onClick={() => runAction("create-change", () => createQmsChange({ ...changeForm, title: changeForm.title || "QMS change" }), "변경 요청을 등록했습니다.")}>변경 등록</Button>
        </CardContent></Card>
        <Card><CardHeader><CardTitle>Release Evidence</CardTitle><CardDescription>브랜치, 커밋, 테스트, 마이그레이션을 기록합니다.</CardDescription></CardHeader><CardContent className="space-y-3">
          <Field label="릴리즈 제목" value={releaseForm.title} onChange={(v) => setReleaseForm({ ...releaseForm, title: v })} />
          <Field label="브랜치" value={releaseForm.branch} onChange={(v) => setReleaseForm({ ...releaseForm, branch: v })} />
          <Field label="커밋 SHA" value={releaseForm.commit_hash} onChange={(v) => setReleaseForm({ ...releaseForm, commit_hash: v })} />
          <Field label="테스트 요약" value={releaseForm.test_summary} onChange={(v) => setReleaseForm({ ...releaseForm, test_summary: v })} textarea />
          <Button onClick={() => runAction("create-release", () => createQmsRelease({ ...releaseForm, title: releaseForm.title || "QMS release evidence" }), "릴리즈 증적을 등록했습니다.")}>릴리즈 등록</Button>
        </CardContent></Card>
        <Card><CardHeader><CardTitle>Supplier Control</CardTitle><CardDescription>API·플랫폼 공급자와 데이터 접근 수준을 관리합니다.</CardDescription></CardHeader><CardContent className="space-y-3">
          <Field label="공급자명" value={supplierForm.name} onChange={(v) => setSupplierForm({ ...supplierForm, name: v })} />
          <Field label="서비스 범위" value={supplierForm.service_scope} onChange={(v) => setSupplierForm({ ...supplierForm, service_scope: v })} textarea />
          <Field label="담당자" value={supplierForm.owner} onChange={(v) => setSupplierForm({ ...supplierForm, owner: v })} />
          <Button onClick={() => runAction("create-supplier", () => createQmsSupplier({ ...supplierForm, name: supplierForm.name || "New supplier" }), "공급자를 등록했습니다.")}>공급자 등록</Button>
        </CardContent></Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <RecordTable title="변경 요청" rows={changes} columns={["title", "status", "risk_level", "requester"]} actionLabel="승인" onAction={(row) => runAction("approve-change", () => updateQmsChange(row.id, { status: "approved", approved_at: new Date().toISOString() }), "변경 요청을 승인했습니다.")} />
        <RecordTable title="릴리즈 증적" rows={releases} columns={["title", "status", "branch", "commit_hash"]} actionLabel="릴리즈완료" onAction={(row) => runAction("release-complete", () => updateQmsRelease(row.id, { status: "released", released_at: new Date().toISOString(), pushed: true }), "릴리즈 증적을 완료 처리했습니다.")} />
        <RecordTable title="공급자" rows={suppliers} columns={["name", "status", "risk_level", "owner"]} actionLabel="검토완료" onAction={(row) => runAction("supplier-review", () => updateQmsSupplier(row.id, { status: "active", last_reviewed_at: new Date().toISOString() }), "공급자를 검토 완료 처리했습니다.")} />
      </div>
    </div>
  );
}

function PhaseFour({ audits, reviews, evidence, auditForm, setAuditForm, reviewForm, setReviewForm, runAction }: any) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-2">
        <Card><CardHeader><CardTitle>Internal Audit</CardTitle><CardDescription>내부심사 범위, 담당자, 발견사항을 관리합니다.</CardDescription></CardHeader><CardContent className="space-y-3">
          <Field label="심사 제목" value={auditForm.title} onChange={(v) => setAuditForm({ ...auditForm, title: v })} />
          <Field label="심사 범위" value={auditForm.scope} onChange={(v) => setAuditForm({ ...auditForm, scope: v })} textarea />
          <Field label="심사자" value={auditForm.auditor} onChange={(v) => setAuditForm({ ...auditForm, auditor: v })} />
          <Button onClick={() => runAction("create-audit", () => createQmsAudit({ ...auditForm, title: auditForm.title || "Internal audit" }), "내부심사를 등록했습니다.")}>내부심사 등록</Button>
        </CardContent></Card>
        <Card><CardHeader><CardTitle>Management Review</CardTitle><CardDescription>KPI, 리스크, CAPA, 공급자 이슈를 경영검토로 묶습니다.</CardDescription></CardHeader><CardContent className="space-y-3">
          <Field label="검토 제목" value={reviewForm.title} onChange={(v) => setReviewForm({ ...reviewForm, title: v })} />
          <Field label="의장" value={reviewForm.chair} onChange={(v) => setReviewForm({ ...reviewForm, chair: v })} />
          <Field label="입력 요약" value={reviewForm.inputs_summary} onChange={(v) => setReviewForm({ ...reviewForm, inputs_summary: v })} textarea />
          <Button onClick={() => runAction("create-review", () => createQmsManagementReview({ ...reviewForm, title: reviewForm.title || "Management review" }), "경영검토를 등록했습니다.")}>경영검토 등록</Button>
        </CardContent></Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <RecordTable title="내부심사" rows={audits} columns={["title", "status", "auditor", "scheduled_at"]} actionLabel="심사완료" onAction={(row) => runAction("audit-complete", () => updateQmsAudit(row.id, { status: "completed", completed_at: new Date().toISOString() }), "내부심사를 완료 처리했습니다.")} />
        <RecordTable title="경영검토" rows={reviews} columns={["title", "status", "chair", "completed_at"]} actionLabel="검토완료" onAction={(row) => runAction("review-complete", () => updateQmsManagementReview(row.id, { status: "completed", completed_at: new Date().toISOString() }), "경영검토를 완료 처리했습니다.")} />
        <RecordTable title="인증 증적" rows={evidence} columns={["title", "evidence_type", "status", "captured_at"]} />
      </div>
    </div>
  );
}

function RecordTable({ title, rows, columns, actionLabel, onAction }: { title: string; rows: any[]; columns: string[]; actionLabel?: string; onAction?: (row: any) => void }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle><CardDescription>{number(rows.length)}건</CardDescription></CardHeader>
      <CardContent className="overflow-x-auto">
        <Table>
          <TableHeader><TableRow>{columns.map((column) => <TableHead key={column}>{column}</TableHead>)}{actionLabel ? <TableHead /> : null}</TableRow></TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id}>
                {columns.map((column) => <TableCell key={column} className="max-w-[220px] truncate">{column === "status" ? <Badge className={statusClass(row[column])}>{row[column]}</Badge> : String(row[column] ?? "-")}</TableCell>)}
                {actionLabel ? <TableCell><Button size="sm" variant="outline" onClick={() => onAction?.(row)}>{actionLabel}</Button></TableCell> : null}
              </TableRow>
            ))}
            {rows.length === 0 ? <TableRow><TableCell colSpan={columns.length + (actionLabel ? 1 : 0)} className="text-sm text-slate-500">등록된 항목이 없습니다.</TableCell></TableRow> : null}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
