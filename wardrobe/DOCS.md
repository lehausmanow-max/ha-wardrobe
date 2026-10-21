# Wardrobe

A shared wardrobe for your household, inside Home Assistant. Each person gets
their own garments, measurements and fit notes; laundry is shared.

## First run

1. Start the app and open **Wardrobe** from the sidebar.
2. Add the people who share it. Fill in their Home Assistant usernames and the
   app opens on the right wardrobe for whoever is logged in.
3. The sidebar entry is visible to non-admin users, so a partner with a regular
   Home Assistant account can use it too.

## Adding garments

Tap **Add**, then add photos with **Camera** (one per tap) or **Gallery**
(several at once): the garment laid flat or on a hanger against a plain light
background, its care label and its brand or size tag, close up and in daylight.
Each photo uploads as soon as it's taken.

- With a photo AI switched on, **Read photos** reads all of them in one go and
  fills in name, category, colours, fabric with percentages, brand, size and
  care. What came from a label or tag is marked; check and save once.
- A label or tag beats the photo: the fibre composition on the care label
  replaces a fabric guessed from the look, and the brand on the tag replaces a
  logo. Bleach is only ever taken from a care label.
- Without AI, **Continue** opens the form with colours read from the photo;
  care defaults come from the fabric you fill in.
- Tap the label under a photo to change what it shows (Garment, Main photo,
  Care label, Tag).
- An unsaved garment is kept as a draft for a day. **Add** offers to continue
  it, for example when the phone closed the browser while the camera was open.

For a garment you already have: **Camera** or **Gallery** on its page adds
photos, and **Re-read photos** reads them again. Changes are shown for you to
tick; values from a label or tag are ticked, what you typed yourself isn't.

Photos are resized to 2048 px on the phone before upload, and saved again on the
server without metadata, so GPS positions never end up in the wardrobe.

Purchase price and date aren't asked for any more. Values entered in earlier
versions are kept and stay in the JSON export.

## What each tab does

**Wardrobe** — everything you own, filterable by category, with what's in the
wash or due for one.

**Looks** — pick an occasion and temperature, get outfits from clean clothes.
Rules behind the score: one accent colour on a neutral base beats several;
one loud pattern per outfit; pieces within one step of formality; layers to
match the temperature; recently worn pieces sink. **Style this** on a garment
builds looks around it. **Build your own** scores a combination as you pick.

**Fit** — your body measurements against each garment's (ease = garment minus
body, judged for the garment's intended fit: slim, regular, relaxed or
oversized), plus notes you log after wearing something. After a few notes it
shows which brands run small or large on you. A photo of you wearing it gets
an AI read on how it fits when a photo AI is on.

**Care** — the wash basket sorted into loads by programme, temperature and
colour group, and garments due a wash based on wears since the last one.

**Shop** — what to buy next, ranked by how many new good outfits each piece
would add to what you own; gaps (rain jacket, winter coat, smart layer, smart
shoes); pieces nothing goes with; pieces not worn in three months; a wishlist.

## Configuration

| Option | What it does |
| --- | --- |
| `ai_vision_provider` | `none`, `ollama` or `claude`. Reads photos: garments with their labels and tags, fit photos. |
| `ai_text_provider` | `none`, `ollama` or `claude`. Picks between suggested looks and writes shopping advice. Sends text only. |
| `ollama_url` | Your Ollama server, e.g. `http://192.168.1.20:11434`. |
| `ollama_vision_model` | A model that reads images: `qwen2.5vl:7b`, `llama3.2-vision`, `gemma3`. |
| `ollama_text_model` | Any chat model: `qwen2.5:7b`, `llama3.1:8b`. |
| `claude_api_key` | From console.anthropic.com, when either provider is `claude`. |
| `claude_model` | `claude-sonnet-5-5` by default; `claude-haiku-5-5` is cheaper and fine for tagging. |
| `weather_entity` | Optional, e.g. `weather.forecast_home`. Fills in the temperature on the Looks tab. |
| `log_level` | `debug`, `info`, `warning` or `error`. |

Everything works with both providers set to `none`; AI only fills in and
explains. If the AI is unreachable, the app says so and carries on with its own
rules.

### Which AI to pick

- **Photos stay home:** `ollama` for vision. A vision model needs a machine with
  a decent GPU (or Apple silicon); a Raspberry Pi or Home Assistant Green is too
  slow. First requests after a model loads can take a minute. Small local
  models read one photo at a time: the main photo for the garment, and each
  photo marked Care label for the care. Mark the label photos before reading.
- **No GPU:** `claude` for vision sends copies of the garment's photos to
  Anthropic's API (up to six, 1568 px, so label text stays readable), nothing
  else about you. Photos of you wearing something are only sent for a fit
  check. Text can still go to a small local model.
- The text provider only ever receives garment names, categories, colour names,
  formality and your style notes.

## Data and backups

Everything lives in the app's `/data` folder (a SQLite database and the photos)
and is included in every Home Assistant backup. **Settings, Backup** in the app
downloads the data as JSON too.

## Troubleshooting

- **Build fails pulling the base image:** edit the `FROM` line in the Dockerfile
  to a dated tag listed at github.com/home-assistant/docker-base.
- **AI requests time out:** check the add-on log; local vision models on CPU can
  exceed a minute. Try a smaller model or `claude-haiku-5-5`.
- **The app opens on the wrong person:** set Home Assistant usernames in the
  app's Settings.
