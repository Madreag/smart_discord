"use client";

import type { ChannelStats } from "@/types/stats";

interface ChannelListProps {
  channels: ChannelStats[];
}

export function ChannelList({ channels }: ChannelListProps) {
  if (channels.length === 0) {
    return (
      <div className="bg-[#2b2d31] rounded-lg p-8 border border-gray-700 text-center">
        <p className="text-gray-400">No channels found</p>
      </div>
    );
  }

  return (
    <div className="bg-[#2b2d31] rounded-lg border border-gray-700 overflow-hidden">
      <table className="w-full">
        <thead className="bg-[#1e1f22]">
          <tr>
            <th className="text-left text-xs text-gray-400 font-medium px-4 py-3">Channel</th>
            <th className="text-right text-xs text-gray-400 font-medium px-4 py-3">Messages</th>
            <th className="text-center text-xs text-gray-400 font-medium px-4 py-3">Status</th>
          </tr>
        </thead>
        <tbody>
          {channels.map((channel) => (
            <tr key={channel.id} className="border-t border-gray-700 hover:bg-[#32353b]">
              <td className="px-4 py-3">
                <span className="text-gray-400">#</span>
                <span className="text-white ml-1">{channel.name}</span>
              </td>
              <td className="px-4 py-3 text-right text-white">
                {channel.message_count.toLocaleString()}
              </td>
              <td className="px-4 py-3 text-center">
                {channel.is_indexed ? (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-500/20 text-green-400">
                    Indexed
                  </span>
                ) : (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-500/20 text-gray-400">
                    Not Indexed
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
