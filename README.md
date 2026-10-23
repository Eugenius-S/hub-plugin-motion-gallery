# Motion Gallery: an Agents Hub plugin

A dashboard of motion examples, like Hub Design but without a canvas. You see a grid of cards, hover one and a short preview plays, click it and the example lands in a chat input: the poster as a picture and the full prompt as text. Nothing is sent: you edit the text and send it yourself.

The interface is in English by default and in Russian when the hub language (`hub.lang`) is Russian ("Галерея движения"); any other language falls back to English. The language is read when a text is drawn, so a switch takes effect without a reload.

## How it works

- **The view** is `#/x/motion-gallery` (the ☰ menu). A search field (words must all match the prompt, the author, the category, the tags or the slug), category chips, tag chips and a counter. A card shows the poster, a category · author line, the duration and the start of the prompt; the title (when the entry has one) is bold above the prompt; the arrow in the corner opens the original post when the entry has one.
- **Hover** plays the preview: muted, looped, one at a time, created only after the mouse rests on a card for a moment and dropped as soon as it leaves (the card goes back to its poster). Posters load lazily, near the screen.
- **A click** puts the example into a chat input. The view inserts into the chat you opened last; if you have several, pick one in the "Insert into chat" box at the top (a view has no chat of its own, so the choice is needed there). The poster is attached the way a screenshot is, the prompt text is appended to what is already typed. An entry without a prompt (a skill) puts its description, install lines and repo.
- **The button before the microphone** in the input of any chat opens the gallery right above that input, without a backdrop: the input stays free and visible, it moves the gallery up as it grows. A click on a card puts the example into that chat at once and the gallery stays open: pick several, keep typing. Picked cards carry a check mark. The cross in the corner, the button again or Escape (in the gallery or in the chat input) closes it.
- It scales to hundreds of entries: the cards are built once, filters only hide them, previews are never preloaded.

## The gallery folder

Set the folder in `hub.json`; until it is set the view is empty and says so:

```json
{ "extensions": { "motion-gallery": { "gallery_dir": "~/motion-gallery" } } }
```

Then `hub restart ext:<account>:motion-gallery` (or "Reload" in the view after the first start). The folder holds:

```
gallery.json
previews/<slug>.mp4      short muted preview, about 480 px wide
posters/<slug>.jpg       poster
```

`gallery.json` is a list (or `{ "items": [...] }`) of entries:

```json
{
  "slug": "kinetic-type-01",
  "title": "Kinetic type intro",
  "category": "Kinetic type",
  "author": "Name",
  "duration": 6.5,
  "tags": ["type", "loop"],
  "prompt": "The full prompt that goes into the chat.",
  "post": "https://example.com/original-post",
  "preview": "previews/kinetic-type-01.mp4",
  "poster": "posters/kinetic-type-01.jpg"
}
```

Where an example comes from is optional: `"sources": ["site-a", "site-b"]` (one example can be found in several places) gives a row of source chips to filter by, and `"pages": { "site-a": "https://…", "site-b": "https://…" }` gives the links to the originals (`↗` opens the first one; a plain `post` / `page` still works). `video` is a full-size clip; when `preview` is not set the card plays it.

The shared gallery of Icons8 writes the same things under other names, and they are read too: `id` for `slug`, `seconds` for `duration`, `prompt_note` as a note, `skill` ({desc, install, repo}) for entries that are a skill and not a prompt, `kind` is ignored. The title is searchable; a prompt can be long (up to 40 000 characters).

Only `slug` (or `id`) and one of `preview` / `poster` are required; a field left out falls back to `previews/<slug>.mp4|webm|mov` and `posters/<slug>.jpg|png|webp`. `preview` and `poster` may be a path inside the folder or an `http(s)` URL (a remote poster is fetched by the plugin process, up to 12 MB), so the files can live on any storage. The file is re-read when it changes.

### Files on the web instead of a folder

If the gallery lives on a storage with a public link, set the base address instead of (or next to) the folder:

```json
{ "extensions": { "motion-gallery": { "media_base": "https://storage.example.com/public/gallery/" } } }
```

A relative path of `gallery.json` that is not in the folder (`previews/x.mp4`, `posters/x.jpg`, `videos/x.mp4`) is then taken from `<media_base>/<path>`; the browser loads previews straight from there. With a base and no folder, `gallery.json` itself is read from `<media_base>/gallery.json` (kept for a minute). The environment variable `MOTION_GALLERY_BASE` overrides the setting. The plugin ships with no address: a public link is a secret of its owner, put it only in your own `hub.json`. A file that is not uploaded yet (a preview, a poster) is not an error: the card stays a calm poster card. Files are fetched by Python first (through the hub proxy, then directly) and, when both fail (for example Python does not trust a certificate that the system does), through `curl`.

## Safety

The plugin process listens on `127.0.0.1` only (hub page port + 12), checks the `Host` header, serves nothing outside the gallery folder and gives the gallery list only to the hub page's own origin. The page reaches it only when opened via `localhost`.

## Install

From the marketplace in the hub (Settings → Plugins, search "Motion Gallery"). The plugin uses the `composer.tools` slot for the chat-input button (a slot of the hub page, button before the microphone); on a hub without that slot the button does not appear and the view works alone. The plugin process takes the hub page port + 12; if that port is busy it exits with a message in the log.

Files shown in the grid (posters, previews) are loaded by the browser straight from their address (the folder or `media_base`); the plugin process fetches only the poster that goes into the chat, and `gallery.json` when there is a base and no folder.

## Tests

```
node --test tests/*.test.mjs
python3 -m unittest discover -s tests
```

The icons of the plugin (close, reload, open, check mark, the view and the input button) are [Icons8 Material](https://icons8.com/icons/material-outlined): outlined, and filled (`icon-filled.svg`) for the hover, where the icon turns filled with a pink/primary gradient (`navicon.css`); with reduced motion it stays still.

Icon — [3D Fluency](https://icons8.com/icons/3d-fluency) from Icons8.

MIT
