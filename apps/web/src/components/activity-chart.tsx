"use client";

import { useMemo } from "react";

interface DataPoint {
  date: string;
  messages: number;
  users: number;
}

interface ActivityChartProps {
  data: DataPoint[];
}

export function ActivityChart({ data }: ActivityChartProps) {
  const maxMessages = useMemo(() => Math.max(...data.map(d => d.messages), 1), [data]);

  if (data.length === 0) {
    return (
      <div className="bg-[#2b2d31] rounded-lg p-8 border border-gray-700 text-center">
        <p className="text-gray-400">No activity data available</p>
      </div>
    );
  }

  return (
    <div className="bg-[#2b2d31] rounded-lg p-4 border border-gray-700">
      <div className="flex items-end gap-1 h-32">
        {data.map((point) => (
          <div
            key={point.date}
            className="flex-1 bg-[#5865f2]/80 hover:bg-[#5865f2] rounded-t transition-colors cursor-pointer group relative"
            style={{ height: `${(point.messages / maxMessages) * 100}%`, minHeight: "4px" }}
            title={`${point.date}: ${point.messages} messages, ${point.users} users`}
          >
            <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 whitespace-nowrap z-10 pointer-events-none">
              {point.messages} msgs
            </div>
          </div>
        ))}
      </div>
      <div className="flex justify-between mt-2 text-xs text-gray-500">
        <span>{data[0]?.date}</span>
        <span>{data[data.length - 1]?.date}</span>
      </div>
    </div>
  );
}
