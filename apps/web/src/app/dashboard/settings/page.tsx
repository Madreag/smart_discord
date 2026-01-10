"use client";

import { useEffect, useState } from "react";

interface ProviderSettings {
  llm_provider: string;
  llm_model: string;
  vision_provider: string;
  vision_model: string;
  embedding_provider: string;
  embedding_model: string;
  has_api_key: boolean;
  has_vision_api_key: boolean;
  has_voyage_api_key: boolean;
  thinking_enabled: boolean;
  thinking_effort: string;
  thinking_budget_tokens: number;
  available_providers: string[];
  available_models: Record<string, string[]>;
  available_vision_models: Record<string, string[]>;
  available_embedding_providers: string[];
  available_embedding_models: Record<string, string[]>;
}

const providerLabels: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  xai: "xAI (Grok)",
};

const embeddingLabels: Record<string, string> = {
  local: "Local (Free)",
  openai: "OpenAI",
  voyage: "Voyage AI",
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<ProviderSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saved" | "error">("idle");

  const fetchSettings = async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${apiUrl}/settings/provider`);
      if (!response.ok) throw new Error("Failed to fetch settings");
      const data = await response.json();
      setSettings(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const updateSettings = async (updates: { llm_provider?: string; llm_model?: string; vision_provider?: string; vision_model?: string; embedding_provider?: string; embedding_model?: string; thinking_enabled?: boolean; thinking_effort?: string; thinking_budget_tokens?: number }) => {
    setSaving(true);
    setSaveStatus("idle");
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const response = await fetch(`${apiUrl}/settings/provider`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || "Failed to update settings");
      }
      const data = await response.json();
      setSettings(data);
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setSaveStatus("error");
    } finally {
      setSaving(false);
    }
  };

  const handleProviderChange = (newProvider: string) => {
    if (!settings) return;
    // When changing provider, also set the first available model for that provider
    const firstModel = settings.available_models[newProvider]?.[0];
    updateSettings({ llm_provider: newProvider, llm_model: firstModel });
  };

  const handleModelChange = (newModel: string) => {
    updateSettings({ llm_model: newModel });
  };

  const handleVisionProviderChange = (newProvider: string) => {
    if (!settings) return;
    // When changing vision provider, set the first available model for that provider
    const firstModel = settings.available_vision_models[newProvider]?.[0];
    updateSettings({ vision_provider: newProvider, vision_model: firstModel });
  };

  const handleVisionModelChange = (newModel: string) => {
    updateSettings({ vision_model: newModel });
  };

  const handleThinkingEnabledChange = (enabled: boolean) => {
    updateSettings({ thinking_enabled: enabled });
  };

  const handleThinkingEffortChange = (effort: string) => {
    updateSettings({ thinking_effort: effort });
  };

  const handleThinkingBudgetChange = (budget: number) => {
    updateSettings({ thinking_budget_tokens: budget });
  };

  const handleEmbeddingProviderChange = (newProvider: string) => {
    if (!settings) return;
    const firstModel = settings.available_embedding_models[newProvider]?.[0];
    updateSettings({ embedding_provider: newProvider, embedding_model: firstModel });
  };

  const handleEmbeddingModelChange = (newModel: string) => {
    updateSettings({ embedding_model: newModel });
  };

  return (
    <main className="min-h-screen bg-discord-darkest">
      {/* Header */}
      <header className="bg-discord-darker border-b border-gray-800">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <a
              href="/dashboard"
              className="text-gray-400 hover:text-white transition-colors"
            >
              ← Back
            </a>
            <h1 className="text-xl font-bold text-white">Settings</h1>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-4xl mx-auto px-4 py-8">
        {/* LLM Provider Settings */}
        <div className="bg-discord-darker rounded-lg overflow-hidden mb-6">
          <div className="px-6 py-4 border-b border-gray-800">
            <h2 className="text-lg font-semibold text-white">
              AI Provider Settings
            </h2>
            <p className="text-sm text-gray-400 mt-1">
              Configure which AI provider to use for queries
            </p>
          </div>

          <div className="p-6 space-y-6">
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
            ) : settings ? (
              <>
                {/* LLM Provider */}
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    LLM Provider
                  </label>
                  <div className="relative">
                    <select
                      value={settings.llm_provider}
                      onChange={(e) => handleProviderChange(e.target.value)}
                      disabled={saving}
                      className={`w-full bg-discord-dark border border-gray-700 rounded-lg px-4 py-3 text-white appearance-none cursor-pointer hover:border-gray-600 focus:border-discord-blurple focus:outline-none transition-colors ${saving ? "opacity-50 cursor-wait" : ""}`}
                    >
                      {settings.available_providers.map((provider) => (
                        <option key={provider} value={provider}>
                          {providerLabels[provider] || provider}
                        </option>
                      ))}
                    </select>
                    <div className="absolute inset-y-0 right-0 flex items-center px-3 pointer-events-none">
                      <svg className="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </div>
                  </div>
                </div>

                {/* Model Selection */}
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Model
                  </label>
                  <div className="relative">
                    <select
                      value={settings.llm_model}
                      onChange={(e) => handleModelChange(e.target.value)}
                      disabled={saving}
                      className={`w-full bg-discord-dark border border-gray-700 rounded-lg px-4 py-3 text-white appearance-none cursor-pointer hover:border-gray-600 focus:border-discord-blurple focus:outline-none transition-colors ${saving ? "opacity-50 cursor-wait" : ""}`}
                    >
                      {settings.available_models[settings.llm_provider]?.map((model) => (
                        <option key={model} value={model}>
                          {model}
                        </option>
                      ))}
                    </select>
                    <div className="absolute inset-y-0 right-0 flex items-center px-3 pointer-events-none">
                      <svg className="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </div>
                  </div>
                  {saveStatus === "saved" && (
                    <p className="text-xs text-green-400 mt-2">Settings saved!</p>
                  )}
                  {saveStatus === "error" && (
                    <p className="text-xs text-red-400 mt-2">Error saving settings</p>
                  )}
                </div>

                {/* API Key Status */}
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    API Key Status
                  </label>
                  <div className={`flex items-center justify-between px-4 py-3 rounded-lg ${
                    settings.has_api_key 
                      ? "bg-green-900/20 border border-green-500/30" 
                      : "bg-red-900/20 border border-red-500/30"
                  }`}>
                    <div className="flex items-center gap-2">
                      <div className={`h-3 w-3 rounded-full ${
                        settings.has_api_key ? "bg-green-500" : "bg-red-500"
                      }`}></div>
                      <span className={settings.has_api_key ? "text-green-400" : "text-red-400"}>
                        {settings.has_api_key ? "API Key Configured" : "No API Key Found"}
                      </span>
                    </div>
                    <a
                      href="/dashboard/api-keys"
                      className="text-sm text-discord-blurple hover:underline"
                    >
                      Manage Keys →
                    </a>
                  </div>
                </div>

                {/* Vision/File Processing Provider */}
                <div className="pt-4 border-t border-gray-700">
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Vision & File Processing Provider
                  </label>
                  <p className="text-xs text-gray-500 mb-3">
                    Used for processing images and documents (PDFs, etc.)
                  </p>
                  <div className="relative">
                    <select
                      value={settings.vision_provider}
                      onChange={(e) => handleVisionProviderChange(e.target.value)}
                      disabled={saving}
                      className={`w-full bg-discord-dark border border-gray-700 rounded-lg px-4 py-3 text-white appearance-none cursor-pointer hover:border-gray-600 focus:border-discord-blurple focus:outline-none transition-colors ${saving ? "opacity-50 cursor-wait" : ""}`}
                    >
                      {settings.available_providers.map((provider) => (
                        <option key={provider} value={provider}>
                          {providerLabels[provider] || provider}
                        </option>
                      ))}
                    </select>
                    <div className="absolute inset-y-0 right-0 flex items-center px-3 pointer-events-none">
                      <svg className="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </div>
                  </div>
                  <div className={`mt-2 flex items-center gap-2 text-xs ${
                    settings.has_vision_api_key ? "text-green-400" : "text-yellow-400"
                  }`}>
                    <div className={`h-2 w-2 rounded-full ${
                      settings.has_vision_api_key ? "bg-green-500" : "bg-yellow-500"
                    }`}></div>
                    {settings.has_vision_api_key 
                      ? "Vision API key configured" 
                      : "No API key for selected vision provider"}
                  </div>
                </div>

                {/* Vision Model Selection */}
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Vision Model
                  </label>
                  <div className="relative">
                    <select
                      value={settings.vision_model}
                      onChange={(e) => handleVisionModelChange(e.target.value)}
                      disabled={saving}
                      className={`w-full bg-discord-dark border border-gray-700 rounded-lg px-4 py-3 text-white appearance-none cursor-pointer hover:border-gray-600 focus:border-discord-blurple focus:outline-none transition-colors ${saving ? "opacity-50 cursor-wait" : ""}`}
                    >
                      {settings.available_vision_models[settings.vision_provider]?.map((model) => (
                        <option key={model} value={model}>
                          {model}
                        </option>
                      ))}
                    </select>
                    <div className="absolute inset-y-0 right-0 flex items-center px-3 pointer-events-none">
                      <svg className="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </div>
                  </div>
                  <p className="text-xs text-gray-500 mt-2">
                    Model used for image captioning and document analysis
                  </p>
                </div>

                {/* Thinking Mode Settings */}
                <div className="pt-4 border-t border-gray-700">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-300">
                        Extended Thinking Mode
                      </label>
                      <p className="text-xs text-gray-500 mt-1">
                        Enable deep reasoning for complex problems (Claude, OpenAI o1/o3, Grok)
                      </p>
                    </div>
                    <button
                      onClick={() => handleThinkingEnabledChange(!settings.thinking_enabled)}
                      disabled={saving}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                        settings.thinking_enabled ? "bg-discord-blurple" : "bg-gray-600"
                      } ${saving ? "opacity-50 cursor-wait" : "cursor-pointer"}`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                          settings.thinking_enabled ? "translate-x-6" : "translate-x-1"
                        }`}
                      />
                    </button>
                  </div>

                  {settings.thinking_enabled && (
                    <>
                      {/* Thinking Effort */}
                      <div className="mb-4">
                        <label className="block text-sm font-medium text-gray-300 mb-2">
                          Thinking Effort
                        </label>
                        <div className="relative">
                          <select
                            value={settings.thinking_effort}
                            onChange={(e) => handleThinkingEffortChange(e.target.value)}
                            disabled={saving}
                            className={`w-full bg-discord-dark border border-gray-700 rounded-lg px-4 py-3 text-white appearance-none cursor-pointer hover:border-gray-600 focus:border-discord-blurple focus:outline-none transition-colors ${saving ? "opacity-50 cursor-wait" : ""}`}
                          >
                            <option value="low">Low - Quick responses</option>
                            <option value="medium">Medium - Balanced</option>
                            <option value="high">High - Deep reasoning</option>
                          </select>
                          <div className="absolute inset-y-0 right-0 flex items-center px-3 pointer-events-none">
                            <svg className="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                            </svg>
                          </div>
                        </div>
                      </div>

                      {/* Budget Tokens (for Claude) */}
                      {settings.llm_provider === "anthropic" && (
                        <div>
                          <label className="block text-sm font-medium text-gray-300 mb-2">
                            Thinking Budget (tokens)
                          </label>
                          <input
                            type="number"
                            value={settings.thinking_budget_tokens}
                            onChange={(e) => handleThinkingBudgetChange(parseInt(e.target.value) || 2000)}
                            min={100}
                            max={50000}
                            disabled={saving}
                            className={`w-full bg-discord-dark border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-discord-blurple focus:outline-none transition-colors ${saving ? "opacity-50 cursor-wait" : ""}`}
                          />
                          <p className="text-xs text-gray-500 mt-2">
                            Claude-specific: How many tokens to allocate for reasoning (100-50,000)
                          </p>
                        </div>
                      )}
                    </>
                  )}
                </div>

                {/* Embedding Provider */}
                <div className="pt-4 border-t border-gray-700">
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Embedding Provider
                  </label>
                  <div className="relative">
                    <select
                      value={settings.embedding_provider}
                      onChange={(e) => handleEmbeddingProviderChange(e.target.value)}
                      disabled={saving}
                      className={`w-full bg-discord-dark border border-gray-700 rounded-lg px-4 py-3 text-white appearance-none cursor-pointer hover:border-gray-600 focus:border-discord-blurple focus:outline-none transition-colors ${saving ? "opacity-50 cursor-wait" : ""}`}
                    >
                      {settings.available_embedding_providers?.map((provider) => (
                        <option key={provider} value={provider}>
                          {embeddingLabels[provider] || provider}
                        </option>
                      ))}
                    </select>
                    <div className="absolute inset-y-0 right-0 flex items-center px-3 pointer-events-none">
                      <svg className="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </div>
                  </div>
                  {settings.embedding_provider === "voyage" && !settings.has_voyage_api_key && (
                    <p className="text-xs text-yellow-500 mt-2">
                      ⚠️ Voyage API key not configured. <a href="/dashboard/settings/keys" className="underline">Add it here</a>
                    </p>
                  )}
                  {settings.embedding_provider === "local" && (
                    <p className="text-xs text-green-500 mt-2">Free, no API key required</p>
                  )}
                </div>

                {/* Embedding Model */}
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Embedding Model
                  </label>
                  <div className="relative">
                    <select
                      value={settings.embedding_model}
                      onChange={(e) => handleEmbeddingModelChange(e.target.value)}
                      disabled={saving}
                      className={`w-full bg-discord-dark border border-gray-700 rounded-lg px-4 py-3 text-white appearance-none cursor-pointer hover:border-gray-600 focus:border-discord-blurple focus:outline-none transition-colors ${saving ? "opacity-50 cursor-wait" : ""}`}
                    >
                      {settings.available_embedding_models?.[settings.embedding_provider]?.map((model) => (
                        <option key={model} value={model}>
                          {model}
                        </option>
                      ))}
                    </select>
                    <div className="absolute inset-y-0 right-0 flex items-center px-3 pointer-events-none">
                      <svg className="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </div>
                  </div>
                  <p className="text-xs text-yellow-600 mt-2">
                    ⚠️ Changing embedding model requires re-indexing your data
                  </p>
                </div>
              </>
            ) : null}
          </div>
        </div>

        {/* Environment Variables Reference */}
        <div className="bg-discord-darker rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-800">
            <h2 className="text-lg font-semibold text-white">
              Configuration Reference
            </h2>
          </div>
          <div className="p-6">
            <p className="text-sm text-gray-400 mb-4">
              Add these to your <code className="bg-discord-dark px-2 py-1 rounded">.env</code> file:
            </p>
            <pre className="bg-discord-dark rounded-lg p-4 text-sm overflow-x-auto">
              <code className="text-gray-300">{`# Choose LLM provider: openai, anthropic, or xai
LLM_PROVIDER=anthropic

# Vision/File processing provider (for images, PDFs)
VISION_PROVIDER=xai

# OpenAI
OPENAI_API_KEY=sk-...

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# xAI (Grok)
XAI_API_KEY=xai-...

# Voyage AI (for embeddings)
VOYAGE_API_KEY=pa-...

# Embeddings: local, openai, or voyage
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=all-MiniLM-L6-v2`}</code>
            </pre>
          </div>
        </div>
      </div>
    </main>
  );
}
