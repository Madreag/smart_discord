"use client";

interface IndexingProgressProps {
  indexed: number;
  pending: number;
  total: number;
  sessions: { indexed: number; total: number };
}

export function IndexingProgress({ indexed, pending, total, sessions }: IndexingProgressProps) {
  const percentage = total > 0 ? (indexed / total) * 100 : 0;
  const sessionPercentage = sessions.total > 0 ? (sessions.indexed / sessions.total) * 100 : 0;

  return (
    <div className="bg-[#2b2d31] rounded-lg p-4 border border-gray-700 space-y-4">
      {/* Messages Progress */}
      <div>
        <div className="flex justify-between text-sm mb-2">
          <span className="text-gray-400">Messages</span>
          <span className="text-white">{indexed.toLocaleString()} / {total.toLocaleString()}</span>
        </div>
        <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-[#5865f2] transition-all duration-500"
            style={{ width: `${Math.min(percentage, 100)}%` }}
          />
        </div>
        {pending > 0 && (
          <p className="text-xs text-yellow-400 mt-1">
            {pending.toLocaleString()} messages pending indexing
          </p>
        )}
      </div>

      {/* Sessions Progress */}
      {sessions.total > 0 && (
        <div>
          <div className="flex justify-between text-sm mb-2">
            <span className="text-gray-400">Sessions</span>
            <span className="text-white">{sessions.indexed.toLocaleString()} / {sessions.total.toLocaleString()}</span>
          </div>
          <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-green-500 transition-all duration-500"
              style={{ width: `${Math.min(sessionPercentage, 100)}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
