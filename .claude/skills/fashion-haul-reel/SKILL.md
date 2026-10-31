---
name: fashion-haul-reel
description: Make a 9:16 Instagram "haul" reel of real discounted fashion products in the parcel-unboxing + wooden-hanger style (typewriter yellow title, parcel drop, hands unboxing, each item held on a hanger against a warm beige wall). Use whenever asked to create a fashion, deal, haul, try-on or "sale clothes" video or reel, or when the daily fashion-deals automation runs.
---

# Fashion haul reel

Recreates the reference style the user picked: a 12–15 s vertical reel where a parcel lands on a
wooden floor while a bold yellow title types in, hands open it, and each item is then shown on a
wooden hanger held up by a hand against a warm beige wall. The products must be **real items with
real prices and links**, never invented ones.

Tools (FlowCast connector, shown as `Video_Create`): `generate_image`, `start_video`, `get_video`,
`join_videos`, `list_files`. Deal and trend research: `Web_Scrapper` (`trends_find`,
`list_extract`); it runs in the user's Chrome through the PullRows extension, so Chrome must be open.
Posting: `DirectApply_DM` (`list_accounts`, `schedule_post`).

## 1. Pick the theme from what is trending

`trends_find` with `platform: "youtube-shorts"`, a query like `"budget fashion haul india"`,
`max_age_days: 7`. Take the clothing type the top results share (for example winter co-ord sets,
leather jackets, festive kurtas, Meesho finds) and the hook wording they use.

## 2. Find real deals

`list_extract` on a store listing sorted by discount, for that clothing type. Working examples:

- Myntra: `https://www.myntra.com/<category>?sort=discount` (e.g. `women-co-ords`, `sweatshirts`)
- Ajio, Flipkart, Amazon, Meesho: their search page for the item with a discount or price-low sort

Keep items with a rating of 4.0 or more, a big discount and sizes in stock. Pick 2–4 that look
different from each other. For each, keep: brand, short name, price, MRP, rating, product link and
the image URL. Myntra image URLs come resized (`.../f_webp,dpr_1.5,q_60,w_210,c_limit,fl_progressive/assets/...`);
drop the part between `assets.myntassets.com/` and `assets/` to get the full-size photo.

## 3. Budget the GPU before generating

Each Hugging Face job counts against the daily ZeroGPU allowance. The free account runs out after
about **3 jobs a day**; Hugging Face PRO gives about 40 minutes (25+ jobs). Plan the shot list to fit:

| Allowance | Shot list |
|---|---|
| Free (~3 jobs) | Model mode, 3 items, no parcel; or parcel + 2 items |
| PRO | Full hanger mode: parcel + unboxing + 3–5 items on hangers |

If a job fails with "exceeded your free ZeroGPU quota", stop generating, join what is finished, and
tell the user. Never loop on retries.

## 4. Make the shots

All clips are 9:16. Start the `start_video` jobs together and poll each `get_video` every ~20 s.

**Opening (parcel), no product needed:**

1. `generate_image`: "Vertical top-down photo of a warm brown wooden plank floor. Two sealed plain
   white courier mailer bags, stacked slightly offset, in the center. Unbranded, no logos, no text.
   Soft daylight, realistic unboxing reel."
2. `start_video` with that `image_file_id`: "A third white mailer bag drops into frame onto the
   stack, then two hands enter from the right and tear the top bag open. Static top-down camera,
   natural motion."

**Each item, hanger mode (matches the reference; 2 jobs per item):**

1. `generate_image` with the product photo in `reference_image_urls` (FLUX.1 Kontext keeps the garment and changes the scene):
   "Show this exact garment alone on a wooden hanger, held up by a hand from the top of the frame,
   in front of a warm beige wall with soft window light, a green potted plant on the left and a
   beige diamond-pattern rug below. Keep the garment's color, print, collar and details exactly
   the same. No person wearing it, no text, no logos."
2. `start_video` with the new `image_file_id`: "The hand holds the hanger and gently turns it side
   to side to show the garment, fabric swaying naturally, smooth slow push-in. Keep the garment
   exactly the same."

**Each item, model mode (1 job per item, for a tight GPU budget):** `start_video` straight on the
store's model photo (`image_url`): "The model in this exact outfit turns slightly side to side and
takes a small step toward the camera, fabric moving naturally. Keep the outfit, colors and
pattern exactly the same. Smooth fashion catalogue reel, steady camera."

## 5. Join

`join_videos` with the clip ids in order (parcel first), plus:

- `title`: the hook, short and in the reference's wording: "3 Beautiful Co-ord Sets",
  "90% OFF Sweatshirts", "Winter Jackets Under 999". The joiner uses a basic font with no ₹ sign,
  so write prices in the title as numbers ("Under 999").
- `subtitle`: `"for you"`

The title types in letter by letter in bold yellow and holds for 3.5 s. Clips come out silent:
tell the user to add a trending sound in Instagram when posting.

## 6. Caption

```
<Hook line with emoji> 😱

1️⃣ <Brand> <short name>: ₹<price> (MRP ₹<mrp>) ⭐<rating>
2️⃣ ...

Comment "LINK" and I'll DM you all <n> 🛍️ Prices as of <date>, sizes are limited!

#<Store>Finds #<ItemType> #BudgetFashion #FashionDeals #AffordableFashion #OOTD
```

Put the product links in the comment-to-DM automation (`schedule_post` → `automation` with
`keywords: ["LINK"]`, `dm_text` listing each item and link), not in the caption.

## 7. Deliver or post

- Give the reel URL straight away and tell the user to download it: the free Render server deletes
  files when it sleeps after 15 idle minutes.
- Posting: only to the account the user chose, and by default `schedule_post` about 3 hours ahead
  so the user can cancel. Never publish immediately unless the user said to.
- Turn on Instagram's "AI info" label: the clips are AI-generated or AI-animated.
- With affiliate links, add `#ad` (India's ASCI rules).

## Rules

- No store or brand logos, watermarks or packaging branding in generated frames. The reference shows
  the store's own logo; do not copy it. Name the store in the caption instead.
- Only real products from the store listing, with prices exactly as listed that day. Never invent
  items, prices, ratings or discounts.
- Never re-run a finished generation to "try again" without the user asking; it spends GPU allowance.
