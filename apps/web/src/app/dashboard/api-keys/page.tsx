"use client";

import { useEffect, useState } from "react";

interface ApiKeyInfo {
  provider: string;
  label: string;
  is_set: boolean;
  masked_value: string | null;
}

interface ApiKeysData {
  keys: ApiKeyInfo[];
}

export default function ApiKeysPage() {
  const [keysData, setKeysData] = useState<ApiKeysData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [newKeyValue, setNewKeyValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<Record<string, "saved" | "error" | null>>({});
  const [visibleKeys, setVisibleKeys] = useState<Record<string, boolean>>({});

  const fetchKeys = async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${apiUrl}/settings/api-keys`);
      if (!response.ok) throw new Error("Failed to fetch API keys");
      const data = await response.json();
      setKeysData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchKeys();
  }, []);

  const handleSaveKey = async (provider: string) => {
    if (!newKeyValue.trim()) return;
    
    setSaving(true);
    setSaveStatus({ ...saveStatus, [provider]: null });
    
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${apiUrl}/settings/api-keys`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, api_key: newKeyValue }),
      });
      
      if (!response.ok) {
        throw new Error("Failed to save API key");
      }
      
      const data = await response.json();
      setKeysData(data);
      setSaveStatus({ ...saveStatus, [provider]: "saved" });
      setEditingKey(null);
      setNewKeyValue("");
      setTimeout(() => setSaveStatus({ ...saveStatus, [provider]: null }), 2000);
    } catch (err) {
      setSaveStatus({ ...saveStatus, [provider]: "error" });
    } finally {
      setSaving(false);
    }
  };

  const toggleVisibility = (provider: string) => {
    setVisibleKeys({ ...visibleKeys, [provider]: !visibleKeys[provider] });
  };

  const startEditing = (provider: string) => {
    setEditingKey(provider);
    setNewKeyValue("");
  };

  const cancelEditing = () => {
    setEditingKey(null);
    setNewKeyValue("");
  };

  return (
    <main className="min-h-screen bg-discord-darkest">
      {/* Header */}
      <header className="bg-discord-darker border-b border-gray-800">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <a
              href="/dashboard/settings"
              className="text-gray-400 hover:text-white transition-colors"
            >
              ← Back to Settings
            </a>
            <h1 className="text-xl font-bold text-white">API Keys</h1>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-4xl mx-auto px-4 py-8">
        <div className="bg-discord-darker rounded-lg overflow-hidden mb-6">
          <div className="px-6 py-4 border-b border-gray-800">
            <h2 className="text-lg font-semibold text-white">
              Manage API Keys
            </h2>
            <p className="text-sm text-gray-400 mt-1">
              Configure API keys for different AI providers. Changes take effect immediately.
            </p>
          </div>

          <div className="p-6 space-y-4">
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-discord-blurple"></div>
              </div>
            ) : error ? (
              <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-4">
                <p className="text-red-400">Error: {error}</p>
                <p className="text-sm text-gray-400 mt-2">
                  Make sure the API server is running on port 8000
                </p>
              </div>
            ) : keysData ? (
              keysData.keys.map((keyInfo) => (
                <div
                  key={keyInfo.provider}
                  className="bg-discord-dark rounded-lg p-4 border border-gray-700"
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <span className="text-white font-medium">{keyInfo.label}</span>
                      <span
                        className={`px-2 py-0.5 rounded text-xs ${
                          keyInfo.is_set
                            ? "bg-green-900/30 text-green-400 border border-green-500/30"
                            : "bg-gray-700 text-gray-400"
                        }`}
                      >
                        {keyInfo.is_set ? "Configured" : "Not Set"}
                      </span>
                      {saveStatus[keyInfo.provider] === "saved" && (
                        <span className="text-green-400 text-xs">Saved!</span>
                      )}
                      {saveStatus[keyInfo.provider] === "error" && (
                        <span className="text-red-400 text-xs">Error saving</span>
                      )}
                    </div>
                  </div>

                  {editingKey === keyInfo.provider ? (
                    <div className="space-y-3">
                      <div className="relative">
                        <input
                          type={visibleKeys[keyInfo.provider] ? "text" : "password"}
                          value={newKeyValue}
                          onChange={(e) => setNewKeyValue(e.target.value)}
                          placeholder={`Enter ${keyInfo.label} API key...`}
                          className="w-full bg-discord-darkest border border-gray-600 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-discord-blurple pr-10"
                          autoFocus
                        />
                        <button
                          type="button"
                          onClick={() => toggleVisibility(keyInfo.provider)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white"
                        >
                          {visibleKeys[keyInfo.provider] ? (
                            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                            </svg>
                          ) : (
                            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                            </svg>
                          )}
                        </button>
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleSaveKey(keyInfo.provider)}
                          disabled={saving || !newKeyValue.trim()}
                          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                            newKeyValue.trim()
                              ? "bg-discord-blurple hover:bg-discord-blurple/80 text-white"
                              : "bg-gray-700 text-gray-400 cursor-not-allowed"
                          } ${saving ? "opacity-50" : ""}`}
                        >
                          {saving ? "Saving..." : "Save"}
                        </button>
                        <button
                          onClick={cancelEditing}
                          className="px-4 py-2 rounded-lg text-sm font-medium bg-gray-700 hover:bg-gray-600 text-white transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {keyInfo.is_set && keyInfo.masked_value ? (
                          <>
                            <code className="bg-discord-darkest px-3 py-1.5 rounded text-gray-400 font-mono text-sm">
                              {visibleKeys[keyInfo.provider] ? keyInfo.masked_value : "••••••••••••"}
                            </code>
                            <button
                              onClick={() => toggleVisibility(keyInfo.provider)}
                              className="text-gray-400 hover:text-white p-1"
                              title={visibleKeys[keyInfo.provider] ? "Hide" : "Show"}
                            >
                              {visibleKeys[keyInfo.provider] ? (
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                                </svg>
                              ) : (
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                                </svg>
                              )}
                            </button>
                          </>
                        ) : (
                          <span className="text-gray-500 text-sm">No API key configured</span>
                        )}
                      </div>
                      <button
                        onClick={() => startEditing(keyInfo.provider)}
                        className="px-3 py-1.5 rounded-lg text-sm font-medium bg-gray-700 hover:bg-gray-600 text-white transition-colors"
                      >
                        {keyInfo.is_set ? "Change" : "Add Key"}
                      </button>
                    </div>
                  )}
                </div>
              ))
            ) : null}
          </div>
        </div>

        {/* Security Notice */}
        <div className="bg-yellow-900/20 border border-yellow-500/30 rounded-lg p-4">
          <div className="flex gap-3">
            <svg className="w-5 h-5 text-yellow-400 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <div>
              <p className="text-yellow-400 font-medium">Security Notice</p>
              <p className="text-sm text-gray-400 mt-1">
                API keys set here are stored in memory only and will reset when the server restarts. 
                For persistent configuration, add keys to your <code className="bg-discord-dark px-1.5 py-0.5 rounded">.env</code> file.
              </p>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
