# Wardrobe

A shared wardrobe for your household, inside Home Assistant. Each person gets
their own garments, measurements and fit notes; laundry is shared.

## First run

1. Start the app and open **Wardrobe** from the sidebar.
2. Add the people who share it. Fill in their Home Assistant usernames and the
   app opens on the right wardrobe for whoever is logged in. The first time
   someone opens the app, their profile is linked to their Home Assistant user;
   from then on the user ID decides, so renaming doesn't break it. Settings shows
   the link and has **Unlink**.
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
- In the Home Assistant Android app there's one **Add photos** button instead:
  that app can't open the camera from a page yet, so take the photos with the
  camera app first and pick them there. Until its next release it also picks
  one photo at a time.
- **Many garments at once:** use Chrome on the phone instead, logged in to
  Home Assistant there (the same address you use in the app). There, Camera
  opens the camera and Gallery picks several photos at once.

For a garment you already have: **Camera** or **Gallery** on its page
(**Add photos** in the Android app) adds photos, and **Re-read photos** reads them again. Changes are shown for you to
tick; values from a label or tag are ticked, what you typed yourself isn't.

Photos are resized to 2048 px on the phone before upload, and saved again on the
server without metadata, so GPS positions never end up in the wardrobe.

Purchase price and date aren't asked for any more. Values entered in earlier
versions are kept and stay in the JSON export.

## What each tab does

The app opens on **Looks**, with today's look; the wardrobe is one tab over.
Tapping the morning notification lands there too.

**Looks** — opens with **Today**: a look for today, picked from clean clothes
for the day's forecast (low and high, and whether rain is likely) and your
calendar (see below). **Wear this** logs it, once a day; **Another** shows the
next of up to eight. It's the same look Home Assistant shows (see below), so the
app and your phone stay in step. On a day without enough clean clothes, Today
says why and has **Add clothes**, which opens the Wardrobe tab; the look is
picked again as soon as there are enough: adding or washing clothes is enough.
Below it, pick an occasion and temperature to get outfits from clean clothes.
Rules behind the score: one accent colour on a neutral base beats several;
one loud pattern per outfit; pieces within one step of formality; layers to
match the temperature; recently worn pieces sink. **Style this** on a garment
builds looks around it. **Build your own** scores a combination as you pick.

**Wardrobe** — everything you own, filterable by category, with what's in the
wash or due for one. **Add** (the round button) adds a garment.

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

## Calendar

Under **Settings**, each person ticks the Home Assistant calendars that count
for their look. Today's look then reads the day's events, all-day events
included, and dresses for the most formal one it recognises: evening or smart
first, then work, then sport. Nothing recognised, or no calendars ticked, means
a casual day. The reason says why, e.g. "Diner at 19:00 in your calendar" or
"Kantoor today".

Events are recognised by whole words in their title, in any case, so
"dinnerware" doesn't count as dinner. The words per occasion are under
**Settings, Words that set the occasion**, comma-separated; English and Dutch
words are set by default, and **Reset to defaults** puts them back.

| Occasion | Default words |
| --- | --- |
| work | office, kantoor, op kantoor, on site, werkdag |
| smart | interview, sollicitatie, presentation, presentatie, client, klant, wedding, bruiloft, funeral, uitvaart, ceremony |
| evening | dinner, diner, etentje, theatre, theater, concert, party, feest, borrel |
| sport | gym, sportschool, training, run, hardlopen, padel, tennis, yoga, zwemmen |

The day's look is picked once, early in the morning; a calendar change later in
the day counts after a `refresh` command (see below). A calendar shared by two
people can simply be ticked for both. When the calendar can't be read, the look
is picked for a casual day and the app log says so once.

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
| `weather_entity` | Optional. Only the entity ID, e.g. `weather.forecast_home`. Fills in the temperature on the Looks tab; its daily forecast picks today's look. Without a daily forecast, the current temperature is used. |
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

## Home Assistant: sensors, events and commands

The app decides **what** to wear; Home Assistant decides **when** and **where**
to show it. The app never sends notifications itself.

### Sensor per person

`sensor.wardrobe_today_<slug>`, where the slug is the person's name in ASCII
lowercase with everything else turned into `_` (a person called "Anna B." gets
`sensor.wardrobe_today_anna_b`). The state is a short summary of the look, or
`none` when there aren't enough clean clothes. Attributes:

| Attribute | |
| --- | --- |
| `profile_id`, `profile` | Who it's for. |
| `items` | `[{id, name, category}]` |
| `reasons`, `warnings` | Why it works (top three), and what to watch. |
| `occasion`, `temp_low`, `temp_high`, `rain`, `condition` | What the look was picked for. |
| `events` | Calendar events that matched: `[{summary, time}]`, time `19:00` or `all day`. |
| `option` | Which of the options is shown, e.g. `2 of 8`. |
| `worn` | Logged as worn today. |
| `image`, `entity_picture` | A picture of the look, `/media/local/wardrobe/look-….jpg`. |
| `generated_at` | When the look last changed. |

States set by an app are lost when Home Assistant restarts; the app sets them
again as soon as it reconnects, and rebuilds every look at 04:00.

The picture is saved in Home Assistant's media folder (`/media/wardrobe`) and
works in Companion app notifications. Pictures older than two days are deleted.

### Today's look on a dashboard

A dashboard card can't load the sensor's `/media/local/...` picture. Each person
also has `/media/wardrobe/today-<slug>.jpg`, which is always their current look
(a plain "No look today" picture when there isn't one). Settings in the app
shows each person's sensor, and so their slug.

**Recommended: a camera on the file.** The card then follows every new look,
Another included, without reloading the dashboard.

1. Settings, Devices & services, Add integration, **Local File**.
2. File path `/media/wardrobe/today-<slug>.jpg`, and a name such as
   "Wardrobe today <name>". This gives a camera entity, e.g.
   `camera.wardrobe_today_<slug>`.
3. Add a picture-entity card on that camera:

```yaml
type: picture-entity
entity: camera.wardrobe_today_<slug>
show_state: false
tap_action:
  action: more-info
  entity: sensor.wardrobe_today_<slug>
```

**Simpler: a picture card.** No integration needed, but it shows the look from
when the dashboard was loaded; reload the page to see a new one.

```yaml
type: picture
image: media-source://media_source/local/wardrobe/today-<slug>.jpg
tap_action:
  action: more-info
  entity: sensor.wardrobe_today_<slug>
```

### Events the app fires

- `wardrobe_look_ready`: `{profile_id, profile, slug, entity_id, summary,
  reason, weather, image, option, options}`, after prepare, next and refresh,
  and after Another in the app. `weather` is a line such as `8–13 °C, rain
  likely`.
- `wardrobe_look_worn`: `{profile_id, profile, slug, items}`, after wear, and
  after Wear this in the app.

### Commands

Fire a `wardrobe_command` event with `profile` (the name, slug or profile ID)
and `action`:

| Action | |
| --- | --- |
| `prepare` | Today's look, built if there isn't one yet. Fires `wardrobe_look_ready`. |
| `next` | The next option. Fires `wardrobe_look_ready`. |
| `wear` | Logs the shown look as worn today, once a day. Fires `wardrobe_look_worn`. |
| `refresh` | Builds today's look again, for example after laundry. Fires `wardrobe_look_ready`. |

To try it, open Developer tools, Events, and fire `wardrobe_command` with:

```yaml
profile: <slug>
action: next
```

The sensor changes, and listening to `wardrobe_look_ready` there shows the
event. An unknown person or action is logged as a warning and ignored.

Settings in the app shows whether the connection to Home Assistant works.
The app log has one line each time a sensor is set, e.g. `Updated today's look
for alex (2 of 8)`.

### Morning notification (blueprint)

Shortly before your phone alarm, a notification with today's look: the picture,
the reason and the weather, and two buttons, **Wear this** and **Another**.
Another replaces the notification with the next look; Wear this logs the wear
and replaces it with "Logged: …". Tapping the notification opens Wardrobe.

1. In the Companion app on the phone, turn on the **Next alarm** sensor
   (Settings, Companion app, Manage sensors). Without it there's nothing to
   time the notification by.
2. Import the blueprint: Settings, Automations & scenes, Blueprints, Import
   blueprint, with this URL:
   `https://raw.githubusercontent.com/lehausmanow-max/ha-wardrobe/main/blueprints/automation/wardrobe/morning_look.yaml`
3. Create one automation per person from it: the person's slug (Settings in the
   app shows their sensor, `sensor.wardrobe_today_<slug>`), their phone, the
   phone's next-alarm sensor, and how many minutes before the alarm (20 by
   default).

It fires once per alarm, when the alarm is that many minutes away. Alarms more
than 18 hours away, and an `unknown` or `unavailable` sensor, are ignored. The
app itself still sends nothing: the automation does.

## Data and backups

Everything lives in the app's `/data` folder (a SQLite database and the photos)
and is included in every Home Assistant backup. **Settings, Backup** in the app
downloads the data as JSON too.

## Troubleshooting

- **Build fails pulling the base image:** edit the `FROM` line in the Dockerfile
  to a dated tag listed at github.com/home-assistant/docker-base.
- **AI requests time out:** check the add-on log; local vision models on CPU can
  exceed a minute. Try a smaller model or `claude-haiku-5-5`.
- **The app opens on the wrong person:** **Unlink** the profile in the app's
  Settings, then open the app once while logged in as the right person.
- **No sensor in Home Assistant:** check Settings in the app for the Home
  Assistant connection, and the app log for warnings.
