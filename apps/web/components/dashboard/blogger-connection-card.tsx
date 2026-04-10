import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BloggerConfig } from "@/lib/types";

function StatusLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 text-sm leading-6 text-slate-700 sm:grid-cols-[132px_minmax(0,1fr)] sm:gap-3">
      <p className="font-medium text-slate-500">{label}</p>
      <p className="min-w-0 break-all rounded-2xl bg-slate-50 px-3 py-2">{value}</p>
    </div>
  );
}

function ResourceSection({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-lg font-semibold text-ink">{title}</h3>
        <p className="mt-1 text-sm leading-6 text-slate-600">{description}</p>
      </div>
      {children}
    </section>
  );
}

export function BloggerConnectionCard({
  config,
  oauthMessage,
  oauthStatus,
}: {
  config: BloggerConfig;
  oauthMessage?: string;
  oauthStatus?: string;
}) {
  const hasClientConfig = config.client_id_configured && config.client_secret_configured;

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardDescription>Google 연동</CardDescription>
        <CardTitle>Blogger, Search Console, GA4 연결</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-3 xl:grid-cols-2">
          <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">OAuth 설정 상태</p>
            <div className="mt-3 space-y-2">
              <StatusLine label="앱 이름" value={config.client_name || "-"} />
              <StatusLine label="클라이언트 ID" value={config.client_id_configured ? "설정됨" : "미설정"} />
              <StatusLine label="클라이언트 시크릿" value={config.client_secret_configured ? "설정됨" : "미설정"} />
              <StatusLine label="리디렉션 URI" value={config.redirect_uri || "-"} />
            </div>
          </div>

          <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">연결 결과</p>
            <div className="mt-3 space-y-2">
              <StatusLine label="Access Token" value={config.access_token_configured ? "연결됨" : "미연결"} />
              <StatusLine label="Refresh Token" value={config.refresh_token_configured ? "연결됨" : "미연결"} />
              <StatusLine label="Google 계정" value={config.connected ? "연결됨" : "미연결"} />
            </div>
          </div>
        </div>

        <div className="rounded-[24px] border border-ink/10 bg-mist px-4 py-4 text-sm leading-7 text-slate-700">
          <p className="font-semibold text-ink">운영 전 확인</p>
          <p className="mt-2">
            Google OAuth 앱이 <strong>Testing</strong> 상태라면 실제로 로그인할 Google 계정을 <strong>Test users</strong>에
            추가해야 합니다. 계속 운영할 서비스라면 Google OAuth 앱을 <strong>Production</strong>으로 전환하는 편이
            안전합니다.
          </p>
        </div>

        <div className="grid gap-3 xl:grid-cols-2">
          <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">요청 Scope</p>
            <div className="mt-3 space-y-2">
              {config.oauth_scopes.map((scope) => (
                <p key={scope} className="break-all rounded-[18px] bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700">
                  {scope}
                </p>
              ))}
            </div>
          </div>

          <div className="rounded-[24px] border border-ink/10 bg-white/70 p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">승인된 Scope</p>
            {config.granted_scopes.length ? (
              <div className="mt-3 space-y-2">
                {config.granted_scopes.map((scope) => (
                  <p key={scope} className="break-all rounded-[18px] bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700">
                    {scope}
                  </p>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-sm leading-7 text-slate-700">아직 승인된 OAuth 권한이 없습니다.</p>
            )}
          </div>
        </div>

        {oauthStatus ? (
          <div
            className={`rounded-[24px] border px-4 py-4 text-sm leading-7 ${
              oauthStatus === "success"
                ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                : "border-rose-200 bg-rose-50 text-rose-900"
            }`}
          >
            {oauthStatus === "success"
              ? "Google OAuth 연결을 완료했습니다."
              : `Google OAuth 연결 중 오류가 발생했습니다.${oauthMessage ? ` ${oauthMessage}` : ""}`}
          </div>
        ) : null}

        {config.connection_error ? (
          <div className="rounded-[24px] border border-amber-200 bg-amber-50 px-4 py-4 text-sm leading-7 text-amber-950">
            {config.connection_error}
          </div>
        ) : null}

        {config.warnings.length ? (
          <div className="rounded-[24px] border border-amber-200 bg-amber-50 px-4 py-4 text-sm leading-7 text-amber-950">
            {config.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          {hasClientConfig && config.authorization_url ? (
            <Button asChild>
              <a href={config.authorization_url}>Google 계정 연결</a>
            </Button>
          ) : (
            <Button disabled>먼저 Client ID / Secret 저장</Button>
          )}
          <Button asChild variant="outline">
            <a href="/guide">Google 설정 가이드</a>
          </Button>
          <Button asChild variant="outline">
            <a href="/analytics">분석 보기</a>
          </Button>
        </div>

        <div className="space-y-8">
          <ResourceSection
            title="가져온 Blogger 블로그"
            description="실제 계정에서 조회한 Blogger 블로그 목록입니다. 여기서 서비스용 블로그를 가져옵니다."
          >
            {config.available_blogs.length === 0 ? (
              <div className="rounded-[24px] border border-dashed border-ink/15 bg-white/50 px-4 py-5 text-sm text-slate-600">
                아직 가져온 Blogger 블로그가 없습니다.
              </div>
            ) : (
              <div className="grid gap-3 2xl:grid-cols-2">
                {config.available_blogs.map((blog) => (
                  <div key={blog.id} className="min-w-0 overflow-hidden rounded-[24px] border border-ink/10 bg-white/70 p-4">
                    <p className="break-words text-base font-semibold text-ink">{blog.name || "(이름 없음)"}</p>
                    <div className="mt-4 space-y-3">
                      <StatusLine label="Blogger ID" value={blog.id} />
                      <StatusLine label="주소" value={blog.url || "-"} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </ResourceSection>

          <ResourceSection
            title="Search Console 속성"
            description="가져온 속성 중 하나를 각 블로그에 매핑해서 사용합니다."
          >
            {config.search_console_sites.length === 0 ? (
              <div className="rounded-[24px] border border-dashed border-ink/15 bg-white/50 px-4 py-5 text-sm text-slate-600">
                아직 Search Console 속성이 없습니다.
              </div>
            ) : (
              <div className="grid gap-3">
                {config.search_console_sites.map((site) => (
                  <div key={site.site_url} className="min-w-0 overflow-hidden rounded-[24px] border border-ink/10 bg-white/70 p-4">
                    <StatusLine label="속성 URL" value={site.site_url} />
                    <div className="mt-3">
                      <StatusLine label="권한" value={site.permission_level || "-"} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </ResourceSection>

          <ResourceSection title="GA4 속성" description="모니터링 화면에서 사용할 Analytics 속성 목록입니다.">
            {config.analytics_properties.length === 0 ? (
              <div className="rounded-[24px] border border-dashed border-ink/15 bg-white/50 px-4 py-5 text-sm text-slate-600">
                아직 GA4 속성이 없습니다.
              </div>
            ) : (
              <div className="grid gap-3 2xl:grid-cols-2">
                {config.analytics_properties.map((property) => (
                  <div key={property.property_id} className="min-w-0 overflow-hidden rounded-[24px] border border-ink/10 bg-white/70 p-4">
                    <p className="break-words text-base font-semibold text-ink">{property.display_name}</p>
                    <div className="mt-4 space-y-3">
                      <StatusLine label="속성 ID" value={property.property_id} />
                      <StatusLine label="계정" value={property.parent_display_name || "-"} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </ResourceSection>
        </div>
      </CardContent>
    </Card>
  );
}
