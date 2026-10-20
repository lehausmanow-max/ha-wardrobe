# Wardrobe for Home Assistant

A Home Assistant app (add-on) for managing a shared household wardrobe:
garments with photos, outfit suggestions, fit assessment, care and laundry,
and shopping suggestions. Runs behind Ingress, so it sits in the sidebar with
Home Assistant's login and needs no open ports.

```
ha-wardrobe/
├── repository.yaml          app repository manifest
├── wardrobe/                the app
│   ├── config.yaml          options, Ingress, sidebar panel
│   ├── Dockerfile           Alpine base, Python venv
│   ├── run.sh               starts uvicorn on the Ingress port
│   ├── DOCS.md              shown in the app's Documentation tab
│   ├── translations/en.yaml option labels
│   └── app/
│       ├── wardrobe/        Python backend (Starlette + SQLite)
│       │   ├── main.py      HTTP API
│       │   ├── matching.py  outfit engine
│       │   ├── fit.py       ease-based fit and brand sizing
│       │   ├── care.py      fabric care defaults, laundry sorter
│       │   ├── shopping.py  next buys, gaps, cost per wear
│       │   ├── colors.py    colour names, neutrals, harmony
│       │   ├── images.py    resize, strip metadata, dominant colours
│       │   ├── ha.py        Ingress user, weather entity
│       │   └── ai/          Ollama and Claude providers, prompts
│       └── static/          UI: one HTML, one CSS, one JS file, no build step
└── dev/
    ├── run_local.sh         run outside Home Assistant
    └── seed_demo.py         demo data with drawn garment photos
```

## Install on Home Assistant OS

**Option A, local app (quickest):**

1. Install the **Samba share** or **Terminal & SSH** app.
2. Copy the `wardrobe` folder into the `addons` share, so you have
   `addons/wardrobe/config.yaml`. Keep `run.sh` with Unix line endings.
3. **Settings, Apps, Install app**, then **Check for updates** in the top-right
   menu. Open **Local apps**, select **Wardrobe**, **Install**.
4. Set options on the **Configuration** tab if you want AI or weather, then
   **Start** and turn on **Show in sidebar**.

The first build takes a few minutes on a Raspberry Pi.

**Option B, from GitHub (for updates):** push this folder to a GitHub
repository, put its URL in `repository.yaml` and `wardrobe/config.yaml`, then add
the URL under **App store, Repositories**. Bump `version` in `config.yaml` to
ship an update.

## Run locally

```sh
cd ha-wardrobe
./dev/run_local.sh                      # http://127.0.0.1:8099
python3 dev/seed_demo.py                # optional demo data
```

Needs Python 3.11+ with `starlette uvicorn python-multipart pillow`. Data goes to
`dev/data/`. Any option can be set as an environment variable, e.g.
`WARDROBE_AI_VISION_PROVIDER=ollama WARDROBE_OLLAMA_URL=http://gpu-box:11434`.

## API

JSON over HTTP under `/api/`; the UI uses nothing else. Main routes:
`/api/garments`, `/api/intake` (photo in, pre-filled garment out),
`/api/suggest`, `/api/looks`, `/api/fit/overview`, `/api/laundry`,
`/api/shopping`, `/api/export`.

## Roadmap

Next steps, roughly in order of value:

- **Photos:** background removal on intake, so cards look uniform and colours read cleaner.
- **Looks:** today's forecast instead of current temperature; a morning
  "what to wear" notification through Home Assistant; packing lists for trips.
- **Home Assistant:** a sensor with today's suggested look; NFC tags on hangers
  to log wears with a tap.
- **Shared items:** scarves, bags and umbrellas both people use.
- **Shopping:** size advice per brand on wishlist items, using your fit notes.
