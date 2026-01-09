"use client";

interface StatsCardProps {
  title: string;
  value: string;
  subtitle?: string;
  trend?: "up" | "down" | "neutral";
}

function TrendIcon({ trend }: { trend: "up" | "down" | "neutral" }) {
  const color = trend === "up" ? "#4ade80" : trend === "down" ? "#f87171" : "#9ca3af";
  
  if (trend === "up") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2">
        <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
        <polyline points="17 6 23 6 23 12" />
      </svg>
    );
  }
  if (trend === "down") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2">
        <polyline points="23 18 13.5 8.5 8.5 13.5 1 6" />
        <polyline points="17 18 23 18 23 12" />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2">
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

export function StatsCard({ title, value, subtitle, trend }: StatsCardProps) {
  return (
    <div className="bg-[#2b2d31] rounded-lg p-4 border border-gray-700">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-400">{title}</p>
        {trend && <TrendIcon trend={trend} />}
      </div>
      <p className="text-2xl font-bold text-white mt-1">{value}</p>
      {subtitle && <p className="text-xs text-gray-500 mt-1">{subtitle}</p>}
    </div>
  );
}
