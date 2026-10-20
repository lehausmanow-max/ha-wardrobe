# Changelog
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
