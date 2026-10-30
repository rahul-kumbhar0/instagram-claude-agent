# FlowCast MCP

An MCP server that gives Claude Google's Flow models through the official Gemini API:

- **Gemini Omni Flash** (`gemini-omni-1.1-flash`): text-to-video, image-to-video, extend
- **Nano Banana 2.1** (`gemini-nano-banana-2.1`): image generation and editing (product photo → scene)

## Tools
| Tool | What it does |
|---|---|
| `generate_image` | Prompt plus optional product photos → new image (9:16 by default) |
| `create_video` | One call: optional first frame from product photo → finished MP4 (waits for it) |
| `start_video` | Prompt plus optional first-frame image → background video job |
| `get_video` | Poll a job; returns the MP4 URL when it's done |
| `extend_video` | Continue a generated clip |
| `list_files` | Everything generated or uploaded |

## Deploy (Render, free tier)
1. In Render: **New → Blueprint** → pick this repo.
2. Set `GEMINI_API_KEY` (from https://aistudio.google.com/apikey). `MCP_SECRET` is generated for you.
3. After deploy, open the service's **Environment** tab and copy `MCP_SECRET`.
4. In claude.ai: **Settings → Connectors → Add custom connector**
   URL: `https://<your-service>.onrender.com/mcp/<MCP_SECRET>`
5. Upload product photos at `https://<your-service>.onrender.com/upload/<MCP_SECRET>`.

## Connect to Claude Code
This repo ships a `.mcp.json` that points Claude Code at the server via the
`FLOWCAST_MCP_URL` environment variable (so the secret never lands in git).

Set the variable to your full MCP URL, then start Claude Code in this repo:

```bash
export FLOWCAST_MCP_URL="https://<your-service>.onrender.com/mcp/<MCP_SECRET>"
```

Or register it globally for your user instead:

```bash
claude mcp add --transport http --scope user flowcast "https://<your-service>.onrender.com/mcp/<MCP_SECRET>"
```

For Claude Code on the web (cloud sessions), add `FLOWCAST_MCP_URL` as a secret
in your cloud environment settings and make sure the network policy allows
`<your-service>.onrender.com`. Verify the connection with `/mcp` inside Claude Code.

## Notes
- Keep the MCP URL private: the secret in the path is the only lock.
- Render's free disk is temporary. Files disappear on redeploy or sleep, so download finished clips.
- The free plan sleeps after 15 minutes idle, and the first request after that takes about 1 minute.
- API usage is billed by Google per generation. It is separate from your Flow subscription credits.
- Override models with the `VIDEO_MODEL` and `IMAGE_MODEL` env vars if Google renames them.
