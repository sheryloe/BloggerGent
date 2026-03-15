"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DashboardPoint } from "@/lib/types";

export function ProcessingChart({ data }: { data: DashboardPoint[] }) {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardDescription>최근 7일</CardDescription>
        <CardTitle>파이프라인 처리 결과</CardTitle>
      </CardHeader>
      <CardContent className="h-[300px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs>
              <linearGradient id="completedFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#234C5A" stopOpacity={0.35} />
                <stop offset="95%" stopColor="#234C5A" stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id="failedFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#E0712C" stopOpacity={0.28} />
                <stop offset="95%" stopColor="#E0712C" stopOpacity={0.01} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(17,33,45,0.08)" />
            <XAxis dataKey="date" stroke="#6b7280" tickLine={false} axisLine={false} />
            <YAxis allowDecimals={false} stroke="#6b7280" tickLine={false} axisLine={false} />
            <Tooltip
              contentStyle={{
                borderRadius: 16,
                border: "1px solid rgba(17,33,45,0.08)",
                background: "rgba(255,249,240,0.96)",
              }}
            />
            <Area type="monotone" dataKey="completed" name="완료" stroke="#234C5A" fill="url(#completedFill)" strokeWidth={2.5} />
            <Area type="monotone" dataKey="failed" name="실패" stroke="#E0712C" fill="url(#failedFill)" strokeWidth={2.5} />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
