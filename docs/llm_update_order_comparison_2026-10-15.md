# LLM vs. pipeline update-order ranking — 2026-10-15

Each system ranked all 30 components from its own knowledge (ChatGPT, Gemini, Ollama) or from a live ReleaseTrain pull (pipeline), with no cross-contamination between them. Prompt and parsing: `scripts/rank_components_llm.py`.

**Not included below (failed/unavailable): openai:gpt-4o-mini, gemini:gemini-2.5-flash.** See raw responses at the bottom.

| component | ollama:llama3.1 | pipeline:releasetrain |
|---|---:|---:|
| ios | 24 | 14 |
| macos | 23 | 8 |
| safari | 18 | 21 |
| android | 25 | 5 |
| windows | 22 | 4 |
| edge | 21 | 22 |
| ubuntu | 28 | 15 |
| debian | 27 | 17 |
| fedora | 26 | 20 |
| arch | 29 | 18 |
| linux | 30 | 2 |
| firefox | 17 | 16 |
| chrome | 16 | 13 |
| brave | 19 | 23 |
| opera | 20 | 24 |
| docker | 6 | 9 |
| kubernetes | 7 | 6 |
| node | 8 | 25 |
| python | 9 | 26 |
| rust | 10 | 12 |
| home assistant | 12 | 27 |
| nextcloud | 13 | 28 |
| wordpress | 14 | 1 |
| postgresql | 1 | 7 |
| mysql | 2 | 11 |
| mongodb | 3 | 29 |
| git | 5 | 10 |
| grafana | 15 | 19 |
| neovim | 11 | 30 |
| gitlab | 4 | 3 |

## Pairwise rank correlation

| pair | Spearman's ρ | Kendall's τ |
|---|---:|---:|
| ollama:llama3.1 vs pipeline:releasetrain | -0.050 | -0.039 |

## Raw responses (unparsed)

### ollama:llama3.1 (attempt 1)
```
[
  "postgresql",
  "mysql",
  "mongodb",
  "linux",
  "debian",
  "fedora",
  "arch",
  "ubuntu",
  "windows",
  "macos",
  "android",
  "ios",
  "chrome",
  "firefox",
  "safari",
  "brave",
  "opera",
  "edge",
  "docker",
  "kubernetes",
  "node",
  "python",
  "rust",
  "git",
  "gitlab",
  "home assistant",
  "nextcloud",
  "wordpress",
  "grafana",
  "neovim",
  "postgresql"
]
```

### ollama:llama3.1 (attempt 2)
```
[
  "postgresql",
  "mysql",
  "mongodb",
  "gitlab",
  "git",
  "docker",
  "kubernetes",
  "node",
  "python",
  "rust",
  "neovim",
  "home assistant",
  "nextcloud",
  "wordpress",
  "grafana",
  "chrome",
  "firefox",
  "safari",
  "brave",
  "opera",
  "edge",
  "windows",
  "macos",
  "ios",
  "android",
  "fedora",
  "debian",
  "ubuntu",
  "arch",
  "linux"
]
```
