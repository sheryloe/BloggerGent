import Link from "next/link";

import { SettingsConsole } from "@/components/dashboard/settings-console";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchBloggerConfig, fetchSettings } from "@/lib/api";

export default async function AdminPage() {
  const [settings, config] = await Promise.all([fetchSettings(), fetchBloggerConfig()]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardDescription>관리</CardDescription>
            <CardTitle>연동 설정 바로가기</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-600">
            <Link href="/settings" className="font-semibold text-sky-700 hover:underline">
              연동 설정으로 이동
            </Link>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>관리</CardDescription>
            <CardTitle>채널 데이터 반영</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-600">연동 완료 후 채널/블로그 목록은 운영 화면에 자동 반영됩니다.</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>예정</CardDescription>
            <CardTitle>광고 운영 기능</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-600">광고 운영 관련 기능은 이 화면에 단계적으로 추가할 예정입니다.</CardContent>
        </Card>
      </div>

      <SettingsConsole settings={settings} config={config} mode="admin" />
    </div>
  );
}
