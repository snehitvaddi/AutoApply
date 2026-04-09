"use client"

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts"

const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444", "#ec4899"]

interface PlatformChartProps {
  data?: { name: string; value: number }[]
}

export function PlatformChart({ data: propData }: PlatformChartProps) {
  if (!propData?.length) {
    return (
      <div className="flex h-full min-h-[280px] items-center justify-center rounded-xl border border-border bg-card p-5">
        <p className="text-sm text-muted-foreground">No platform data yet.</p>
      </div>
    )
  }

  const data = propData.map((d, i) => ({
    ...d,
    color: COLORS[i % COLORS.length],
  }))
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h3 className="mb-4 text-sm font-medium text-card-foreground">By Platform</h3>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={50}
              outerRadius={70}
              paddingAngle={3}
              dataKey="value"
            >
              {data.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                backgroundColor: "#1e293b",
                border: "1px solid #334155",
                borderRadius: "8px",
                fontSize: "12px",
              }}
              labelStyle={{ color: "#f8fafc" }}
              formatter={(value: number) => [`${value}%`, ""]}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        {data.map((item) => (
          <div key={item.name} className="flex items-center gap-2">
            <div
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: item.color }}
            />
            <span className="text-xs text-muted-foreground">{item.name}</span>
            <span className="ml-auto text-xs font-medium text-card-foreground">
              {item.value}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
