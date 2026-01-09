"use client";

import { useState, useEffect } from "react";

interface PrePromptEditorProps {
  guildId: string;
}

export function PrePromptEditor({ guildId }: PrePromptEditorProps) {
  const [prePrompt, setPrePrompt] = useState("");
  const [savedPrePrompt, setSavedPrePrompt] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [status, setStatus] = useState<"idle" | "saved" | "error">("idle");

  useEffect(() => {
    async function fetchPrePrompt() {
      try {
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        const response = await fetch(`${apiUrl}/guilds/${guildId}/pre-prompt`);
        if (response.ok) {
          const data = await response.json();
          setPrePrompt(data.pre_prompt || "");
          setSavedPrePrompt(data.pre_prompt || "");
        }
      } catch (error) {
        console.error("Error fetching pre-prompt:", error);
      } finally {
        setIsLoading(false);
      }
    }
    fetchPrePrompt();
  }, [guildId]);

  const handleSave = async () => {
    setIsSaving(true);
    setStatus("idle");

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${apiUrl}/guilds/${guildId}/pre-prompt`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ pre_prompt: prePrompt }),
      });

      if (response.ok) {
        setSavedPrePrompt(prePrompt);
        setStatus("saved");
        setTimeout(() => setStatus("idle"), 2000);
      } else {
        setStatus("error");
      }
    } catch (error) {
      console.error("Error saving pre-prompt:", error);
      setStatus("error");
    } finally {
      setIsSaving(false);
    }
  };

  const hasChanges = prePrompt !== savedPrePrompt;

  return (
    <div className="bg-discord-darker rounded-lg overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-800">
        <h2 className="text-lg font-semibold text-white">Bot Personality</h2>
        <p className="text-sm text-gray-400 mt-1">
          Set a pre-prompt to give your bot a custom personality and rules
        </p>
      </div>

      <div className="p-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-discord-blurple"></div>
          </div>
        ) : (
          <>
            <textarea
              value={prePrompt}
              onChange={(e) => setPrePrompt(e.target.value)}
              placeholder="Example: You are a sarcastic but helpful assistant named Botty. Always respond with dry humor while still being informative. Never use emojis."
              className="w-full h-40 bg-discord-dark border border-gray-700 rounded-lg px-4 py-3 text-white placeholder-gray-500 resize-none focus:outline-none focus:border-discord-blurple transition-colors"
            />
            
            <div className="mt-4 flex items-center justify-between">
              <p className="text-xs text-gray-500">
                This text is injected at the start of every conversation with the bot.
              </p>
              
              <div className="flex items-center gap-3">
                {status === "saved" && (
                  <span className="text-green-400 text-sm">Saved!</span>
                )}
                {status === "error" && (
                  <span className="text-red-400 text-sm">Error saving</span>
                )}
                <button
                  onClick={handleSave}
                  disabled={isSaving || !hasChanges}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                    hasChanges
                      ? "bg-discord-blurple hover:bg-discord-blurple/80 text-white"
                      : "bg-gray-700 text-gray-400 cursor-not-allowed"
                  } ${isSaving ? "opacity-50" : ""}`}
                >
                  {isSaving ? "Saving..." : "Save Changes"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
