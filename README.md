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
Register the server once for your user (keep the URL private, it contains the secret):

```bash
claude mcp add --transport http --scope user flowcast "https://<your-service>.onrender.com/mcp/<MCP_SECRET>"
```

On claude.ai, add the same URL under Settings → Connectors → Add custom connector. Verify with `/mcp`.

## Free open-source provider (Hugging Face)
Set `PROVIDER=hf` and `HF_TOKEN` (from https://huggingface.co/settings/tokens) to use free
open-source models on Hugging Face ZeroGPU Spaces instead of Gemini:

- Images: FLUX.1-schnell (`HF_IMAGE_SPACES`)
- Videos: Wan 2.2 image-to-video (`HF_VIDEO_SPACES`, comma-separated, tried in order)

Same tools, no code changes. Notes: free Hugging Face accounts get a small daily GPU quota
(a few short clips); busy Spaces queue; FLUX ignores reference photos, but a product photo
passed to `start_video`/`create_video` is animated directly; `extend_video` is Gemini-only.

## Reels
`join_videos(file_ids, title)` joins clips in order into one 720x1280 reel, with an optional
yellow title over the first 2.5 seconds. The same is available in a browser:
`https://<your-service>.onrender.com/reel/<MCP_SECRET>?ids=<id1>,<id2>,...&title=My%20Haul`

On redeploy, the new instance copies files from the previous one before it starts, so
clips survive deploys (they are still lost when the free service sleeps).

## Fashion haul reels (skill)
`.claude/skills/fashion-haul-reel/SKILL.md` is the recipe Claude follows to turn real discounted
products into a parcel-unboxing + hanger-showcase reel. With `PROVIDER=hf`, `generate_image` with a
reference photo uses FLUX.1 Kontext (`HF_EDIT_SPACES`) to put the exact product into a new scene,
and `join_videos(title, subtitle)` types the title in letter by letter.
