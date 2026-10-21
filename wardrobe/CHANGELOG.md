# Changelog
## 0.3.0

- Add a garment from several photos at once: the garment, its care label and
  its brand or size tag. Camera takes one per tap, Gallery picks several. One
  read fills in the details, including brand, size, fibre composition and care
  from the labels; what came from a label or tag is marked, and you save once.
- A label or tag beats the photo: fibre composition from the care label
  replaces a fabric guessed from the look, the brand on the tag replaces a logo.
- Tap the label under a photo to say what it shows: Garment, Main photo, Care
  label or Tag.
- Existing garments: add photos with Camera or Gallery, then Re-read photos.
  Changes are shown for you to tick; values from a label or tag are ticked,
  what you typed yourself isn't.
- A garment you started but didn't save is kept as a draft for a day, so you
  can continue it, for example after the phone closed the browser while you
  were taking photos. Leaving with two or more photos asks before discarding.
- Purchase price and bought-on are hidden. Stored values are kept and stay in
  the export. Cost per wear is gone from the shopping page.
- Read care label is replaced by Re-read photos.
- Fix: a fibre composition read from a label now replaces the guess from the
  photo.
- The app restarts by itself if it stops responding, and is built on a pinned
  base image.
- No database migration; going back to 0.2.1 stays safe. In 0.2.1, unfinished
  drafts would show as garments and tag photos would be captioned Worn.
## 0.2.1

- Glass themes such as Frosted Glass now carry over: the theme's background
  picture shows behind the app, and cards are frosted glass with the theme's
  edges and shadows. Cards get a light tint so garment names stay readable over
  bright parts of the picture.
- The top bar, bottom menu and garment sheets keep a strong frosted tint, so
  they stay readable over photos. The bottom menu was see-through in 0.2.0.
- Text on the theme's main colour (Wore it today, Add, selected chips) now
  picks dark or light for contrast instead of the theme's text colour.
- A garment sheet's title bar no longer scrolls over its content.
- No database migration.
## 0.2.0

- Follows your Home Assistant theme: colours, dark mode, card corners and font
  now come from the theme you use in Home Assistant, and change with it. For the
  app's own colours, pick Auto, Light or Dark under Settings, Appearance.
- Swiping back (or the Android back button) on a garment now closes the
  garment and returns to the list, one step at a time, instead of leaving the
  app.
- Favourite is a small star: next to the garment's name in the header, so you
  can tap it without editing, and next to the name field when editing.
- Bleach is no longer a choice in the care fields and no longer comes from the
  fabric defaults. It shows only when it was read from a care label photo.
- Settings now shows the installed version, and the browser always loads the
  new screens after an update.
- No database migration; going back to 0.1.1 stays safe.
## 0.1.1

- Now installed from GitHub; no functional changes.
## 0.1.0

First version.

- Profiles per person, matched to Home Assistant users; laundry shared.
- Garments with photos, colours read from the photo, care defaults by fabric.
- Rule-based look suggestions using colour harmony, pattern, formality,
  temperature and rotation; build-your-own with live scoring; saved looks.
- Fit from measurements (ease by intended fit), fit notes, brand sizing, photo
  fit check.
- Laundry sorter and wash-due tracking.
- Shopping: next buys ranked by outfits unlocked, gaps, hard-to-style pieces,
  cost per wear, wishlist.
- Optional AI (Ollama or Claude) for photo tagging, care labels, fit critique,
  look picks and shopping advice.
