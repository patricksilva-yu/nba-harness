import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const h = React.createElement;
const defaultQuestion = "Why did the Knicks beat the Cavs last night?";
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

function apiUrl(path) {
  return `${API_BASE_URL}${path}`;
}

function markdownToBlocks(markdown) {
  if (!markdown) return [];
  return markdown.split("\n").map((line, index) => {
    const trimmed = line.trim();
    if (trimmed.startsWith("# ")) return h("h1", { key: index }, renderInlineMarkdown(trimmed.slice(2)));
    if (trimmed.startsWith("## ")) return h("h2", { key: index }, renderInlineMarkdown(trimmed.slice(3)));
    if (trimmed.startsWith("### ")) return h("h3", { key: index }, renderInlineMarkdown(trimmed.slice(4)));
    if (trimmed.startsWith("- ")) return h("p", { key: index, className: "bullet-line" }, renderInlineMarkdown(trimmed.slice(2)));
    if (!line.trim()) return h("div", { key: index, className: "space-line" });
    return h("p", { key: index }, renderInlineMarkdown(line));
  });
}

function renderInlineMarkdown(text) {
  const nodes = [];
  const pattern = /(\*\*[^*]+\*\*)/g;
  let cursor = 0;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    nodes.push(h("strong", { key: `${match.index}-${match[0]}` }, match[0].slice(2, -2)));
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function StructuredAnalysis({ analysis, evidence = [] }) {
  if (!analysis) return null;
  const sections = [
    ["What decided it", analysis.deciding_factors],
    ["Player findings", analysis.player_findings],
    ["Decisive windows", analysis.decisive_windows],
    ["Limitations", analysis.limitations],
  ];
  const evidenceById = new Map(evidence.map((item) => [item.packet_id, item]));
  return h(
    "div",
    { className: "structured-analysis" },
    h("h1", null, analysis.headline),
    h("p", { className: "analysis-summary" }, analysis.summary),
    ...sections.filter(([, values]) => values?.length).map(([title, values]) =>
      h("section", { key: title }, h("h2", null, title), h("ul", null, ...values.map((value, index) => h("li", { key: index }, value)))),
    ),
    analysis.citations?.length
      ? h(
          "section",
          { className: "evidence-list" },
          h("h2", null, "Evidence"),
          ...analysis.citations.map((citation) => {
            const detail = evidenceById.get(citation.packet_id);
            return h(
              "details",
              { key: citation.packet_id },
              h("summary", null, citation.claim),
              h("code", null, citation.packet_id),
              detail?.payload?.packet?.source_provider ? h("p", null, `Source: ${detail.payload.packet.source_provider}`) : null,
            );
          }),
        )
      : null,
  );
}

function modeOptions(config) {
  const hasApiKey = Boolean(config?.has_api_key);
  const hasAgents = Boolean(config?.has_agents_sdk);
  const hasOpenAI = Boolean(config?.has_openai_sdk);
  const hasRemote = Boolean(config?.remote_mcp_url);
  return [
    {
      value: "responses_tools",
      label: "OpenAI Responses",
      disabled: !(hasApiKey && hasOpenAI),
    },
    {
      value: "local_agents_sdk_mcp",
      label: "Legacy Local MCP",
      disabled: !(hasApiKey && hasAgents),
    },
    {
      value: "remote_responses_mcp",
      label: "OpenAI Remote MCP",
      disabled: !(hasApiKey && hasOpenAI && hasRemote),
    },
    { value: "deterministic", label: "Deterministic", disabled: false },
  ];
}

function splitLabel(label = "") {
  const [away = "", home = ""] = label.split(",").map((part) => part.trim());
  const parseTeam = (part) => {
    const tokens = part.split(/\s+/);
    const score = tokens.pop() || "";
    return { team: tokens.join(" "), score };
  };
  return { away: parseTeam(away), home: parseTeam(home) };
}

function RecentGames({ games, loading, selectedGameId, onSelect, onRefresh }) {
  return h(
    "section",
    { className: "scoreboard-panel", "aria-label": "Recent scoreboards" },
    h(
      "header",
      { className: "scoreboard-header" },
      h("div", null, h("p", { className: "eyebrow" }, "Recent finals"), h("h2", null, "Scoreboards")),
      h("button", { type: "button", className: "ghost-button", onClick: onRefresh, disabled: loading }, loading ? "Loading" : "Refresh"),
    ),
    games.length
      ? h(
          "ol",
          { className: "scoreboard-list" },
          games.map((game) => h(ScoreboardCard, { key: game.game_id, game, selected: selectedGameId === game.game_id, onSelect })),
        )
      : h("p", { className: "muted recent-empty" }, loading ? "Loading recent games..." : "No recent scoreboards loaded."),
  );
}

function ScoreboardCard({ game, selected, onSelect }) {
  const { away, home } = splitLabel(game.label);
  const awayScore = Number(away.score);
  const homeScore = Number(home.score);
  const awayWon = Number.isFinite(awayScore) && Number.isFinite(homeScore) && awayScore > homeScore;
  const homeWon = Number.isFinite(awayScore) && Number.isFinite(homeScore) && homeScore > awayScore;

  return h(
    "li",
    null,
    h(
      "button",
      {
        type: "button",
        className: `scoreboard-card ${selected ? "selected" : ""}`,
        onClick: () => onSelect(game),
      },
      h("span", { className: "game-date" }, game.game_date),
      h("span", { className: `team-row ${awayWon ? "winner" : ""}` }, h("span", null, away.team), h("strong", null, away.score)),
      h("span", { className: `team-row ${homeWon ? "winner" : ""}` }, h("span", null, home.team), h("strong", null, home.score)),
      h("span", { className: "game-id" }, game.game_id),
    ),
  );
}

function App() {
  const [question, setQuestion] = useState(defaultQuestion);
  const [mode, setMode] = useState("responses_tools");
  const [gameId, setGameId] = useState("");
  const [seasonType, setSeasonType] = useState("Auto");
  const [maxEvidence, setMaxEvidence] = useState(4);
  const [persist, setPersist] = useState(false);
  const [loading, setLoading] = useState(false);
  const [recentLoading, setRecentLoading] = useState(false);
  const [recentGames, setRecentGames] = useState([]);
  const [openaiConfig, setOpenaiConfig] = useState(null);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  async function loadRecentGames() {
    setRecentLoading(true);
    setError("");
    try {
      const response = await fetch(apiUrl(`/api/recent-games?season_type=${encodeURIComponent(seasonType)}&limit=8`));
      if (!response.ok) throw new Error(`Recent games failed with ${response.status}`);
      const data = await response.json();
      setRecentGames(data.games || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load recent games");
    } finally {
      setRecentLoading(false);
    }
  }

  async function loadOpenAIConfig() {
    try {
      const response = await fetch(apiUrl("/api/openai-agent/config"));
      if (!response.ok) throw new Error(`OpenAI config failed with ${response.status}`);
      setOpenaiConfig(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load OpenAI config");
    }
  }

  useEffect(() => {
    loadRecentGames();
  }, [seasonType]);

  useEffect(() => {
    loadOpenAIConfig();
  }, []);

  function selectRecentGame(game) {
    setGameId(game.game_id);
    setQuestion(`Why did ${game.label} happen?`);
  }

  function updateQuestion(value) {
    setQuestion(value);
    setGameId("");
  }

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch(apiUrl("/api/ask"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          mode,
          game_id: gameId || null,
          season_type: seasonType,
          max_evidence: Number(maxEvidence),
          persist,
        }),
      });
      if (!response.ok) throw new Error(`Request failed with ${response.status}`);
      setResult(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  return h(
    "main",
    { className: "shell" },
    h(
      "section",
      { className: "query-panel", "aria-label": "Ask the analyst" },
      h(
        "div",
        { className: "brand-row" },
        h("div", null, h("p", { className: "eyebrow" }, "NBA Analyst Agent"), h("h1", null, "Recent scores, clean answers.")),
        h("div", { className: `status-pill ${loading ? "running" : ""}` }, loading ? "Running" : "Ready"),
      ),
      h(
        "form",
        { className: "ask-form", onSubmit: submit },
        h(
          "div",
          { className: "input-row" },
          h("textarea", {
            id: "question",
            rows: 3,
            spellCheck: true,
            value: question,
            onChange: (event) => updateQuestion(event.target.value),
          }),
          h(
            "button",
            { type: "submit", disabled: loading || question.trim().length < 3 },
            h("span", null, loading ? "Wait" : "Run"),
            h("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" }, h("path", { d: "M5 12h12M13 6l6 6-6 6" })),
          ),
        ),
        h(
          "details",
          { className: "options" },
          h("summary", null, "Options"),
          h(
            "div",
            { className: "option-grid" },
            h(
              "label",
              null,
              "Game ID",
              h(
                "div",
                { className: "inline-control" },
                h("input", { value: gameId, onChange: (event) => setGameId(event.target.value), placeholder: "optional" }),
                gameId ? h("button", { type: "button", className: "mini-button", onClick: () => setGameId("") }, "Clear") : null,
              ),
            ),
            h(
              "label",
              null,
              "Mode",
              h(
                "select",
                { value: mode, onChange: (event) => setMode(event.target.value) },
                modeOptions(openaiConfig).map((option) =>
                  h("option", { key: option.value, value: option.value, disabled: option.disabled }, option.label),
                ),
              ),
            ),
            h("label", null, "Season Type", h("select", { value: seasonType, onChange: (event) => setSeasonType(event.target.value) }, h("option", null, "Auto"), h("option", null, "Playoffs"), h("option", null, "Regular Season"))),
            h("label", null, "Evidence Items", h("input", { type: "number", min: 0, max: 12, value: maxEvidence, onChange: (event) => setMaxEvidence(event.target.value) })),
            h("label", { className: "check-label" }, h("input", { type: "checkbox", checked: persist, onChange: (event) => setPersist(event.target.checked) }), "Persist evidence"),
          ),
        ),
      ),
    ),
    error ? h("div", { className: "error-strip" }, error) : null,
    h(
      "section",
      { className: "workspace" },
      h(RecentGames, {
        games: recentGames,
        loading: recentLoading,
        selectedGameId: gameId,
        onSelect: selectRecentGame,
        onRefresh: loadRecentGames,
      }),
      h(
        "article",
        { className: "chat-panel" },
        h("div", { className: "panel-header" }, h("p", { className: "eyebrow" }, "Chat"), result?.resolution?.label ? h("span", { className: "context-pill" }, result.resolution.label) : null),
        h(
          "div",
          { className: "chat-thread" },
          h("div", { className: "message user-message" }, question),
          h(
            "div",
            { className: `message analyst-message ${result ? "" : "empty"}` },
            result
              ? result.analysis
                ? h(StructuredAnalysis, { analysis: result.analysis, evidence: result.evidence })
                : markdownToBlocks(result.answer_markdown)
              : "Pick a recent final or ask a question to get an analyst read.",
          ),
        ),
      ),
    ),
  );
}

createRoot(document.getElementById("root")).render(h(App));
