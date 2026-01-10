"use client";

import { useState } from "react";

interface ChannelToggleProps {
  channelId: string;
  channelName: string;
  guildId: string;
  initialIndexed: boolean;
}

export function ChannelToggle({
  channelId,
  channelName,
  guildId,
  initialIndexed,
}: ChannelToggleProps) {
  const [isIndexed, setIsIndexed] = useState(initialIndexed);
  const [isLoading, setIsLoading] = useState(false);
  const [isReindexing, setIsReindexing] = useState(false);
  const [reindexStatus, setReindexStatus] = useState<string | null>(null);

  const handleToggle = async () => {
    setIsLoading(true);
    const newValue = !isIndexed;

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(
        `${apiUrl}/guilds/${guildId}/channels/${channelId}/index`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ isIndexed: newValue }),
        }
      );

      if (response.ok) {
        setIsIndexed(newValue);
      } else {
        console.error("Failed to toggle indexing");
      }
    } catch (error) {
      console.error("Error toggling indexing:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleReindex = async () => {
    setIsReindexing(true);
    setReindexStatus(null);

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(
        `${apiUrl}/guilds/${guildId}/channels/${channelId}/reindex`,
        {
          method: "POST",
        }
      );

      if (response.ok) {
        const data = await response.json();
        setReindexStatus(`Queued ${data.messages_reset} messages`);
        setTimeout(() => setReindexStatus(null), 3000);
      } else {
        setReindexStatus("Failed");
        setTimeout(() => setReindexStatus(null), 3000);
      }
    } catch (error) {
      console.error("Error triggering reindex:", error);
      setReindexStatus("Error");
      setTimeout(() => setReindexStatus(null), 3000);
    } finally {
      setIsReindexing(false);
    }
  };

  return (
    <div className="px-6 py-4 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-gray-400">#</span>
        <span className="text-white">{channelName}</span>
      </div>
      <div className="flex items-center gap-4">
        {isIndexed && (
          <button
            onClick={handleReindex}
            disabled={isReindexing}
            className={`px-3 py-1 text-xs rounded-md transition-colors ${
              isReindexing
                ? "bg-gray-700 text-gray-400 cursor-wait"
                : reindexStatus
                ? "bg-green-600/20 text-green-400"
                : "bg-discord-blurple/20 text-discord-blurple hover:bg-discord-blurple/30"
            }`}
          >
            {isReindexing ? "Queuing..." : reindexStatus || "Reindex"}
          </button>
        )}
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={isIndexed}
            onChange={handleToggle}
            disabled={isLoading}
            className="sr-only peer"
          />
          <div
            className={`w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-discord-blurple ${
              isLoading ? "opacity-50" : ""
            }`}
          ></div>
          <span className="ml-3 text-sm text-gray-400 w-20">
            {isLoading ? "Saving..." : isIndexed ? "Indexed" : "Not Indexed"}
          </span>
        </label>
      </div>
    </div>
  );
}
