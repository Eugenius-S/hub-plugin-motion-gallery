# Motion Gallery: an Agents Hub plugin

A dashboard of motion examples, like Hub Design but without a canvas. You see a grid of cards, hover one and a short preview plays, click it and the example lands in a chat input: the poster as a picture and the full prompt as text. Nothing is sent: you edit the text and send it yourself.

The interface is in English by default and in Russian when the hub language (`hub.lang`) is Russian ("Галерея движения"); any other language falls back to English. The language is read when a text is drawn, so a switch takes effect without a reload.

## How it works

- **The view** is `#/x/motion-gallery` (the ☰ menu). A search field (words must all match the prompt, the author, the category, the tags or the slug), category chips, tag chips and a counter. A card shows the poster, a category · author line, the duration and the start of the prompt; `↗` opens the original post when the entry has one.
- **Hover** plays the preview: muted, looped, one at a time, created only after the mouse rests on a card for a moment and dropped as soon as it leaves (the card goes back to its poster). Posters load lazily, near the screen.
- **A click** puts the example into a chat input. The view inserts into the chat you opened last; if you have several, pick one in the "Insert into" box at the top. The button before the microphone in the input of any chat opens the gallery over the page and inserts into that very chat. The poster is attached the way a screenshot is, the prompt text is appended to what is already typed.
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

Only `slug` and one of `preview` / `poster` are required; a field left out falls back to `previews/<slug>.mp4|webm|mov` and `posters/<slug>.jpg|png|webp`. `preview` and `poster` may be a path inside the folder or an `http(s)` URL (a remote poster is fetched by the plugin process, up to 12 MB), so the files can live on any storage. The file is re-read when it changes.

## Safety

The plugin process listens on `127.0.0.1` only (hub page port + 12), checks the `Host` header, serves nothing outside the gallery folder and gives the gallery list only to the hub page's own origin. The page reaches it only when opened via `localhost`.

## Install

From the marketplace in the hub (Settings → Plugins, search "Motion Gallery"). The plugin uses the `composer.tools` slot for the chat-input button; on a hub without that slot the view works alone.

## Tests

```
node --test tests/*.test.mjs
python3 -m unittest discover -s tests
```

Icon — [3D Fluency](https://icons8.com/icons/3d-fluency) from Icons8.

MIT
