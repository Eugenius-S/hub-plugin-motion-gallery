// Hub Motion Gallery: put a picture and a text into the input of a session chat, send nothing.
// The page has no call for "set the draft of the open chat" (only for inputs a plugin builds itself), so this goes the way
// the owner would: the picture is pasted into the textarea as a clipboard file (the page uploads it, marks it "[Image #N]",
// shows the chip), then the text is appended to what is typed. Nothing is submitted: the owner edits and sends.

// the picture arrives in the page's own paste handling; false - the browser can not make a synthetic paste
export function pasteFile(ta, file) {
  try {
    const dt = new DataTransfer();
    dt.items.add(file);
    const ev = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true });
    if (!ev.clipboardData || !ev.clipboardData.files.length) return false;   // a browser that drops clipboardData from the constructor
    ta.dispatchEvent(ev);
    return true;
  } catch { return false; }
}

// the text after what is typed (a new line between); the page learns of it by the input event
export function appendText(ta, text) {
  if (!text) return;
  ta.value = ta.value && !/\n$/.test(ta.value) ? ta.value + "\n" + text : ta.value + text;
  ta.dispatchEvent(new Event("input", { bubbles: true }));
  ta.setSelectionRange?.(ta.value.length, ta.value.length);
}

// {text, file?} -> {file: bool (the picture went in), text: bool}
export function insertInto(form, { text = "", file = null } = {}) {
  const ta = form?.querySelector("textarea");
  if (!ta) return { file: false, text: false };
  const gotFile = file ? pasteFile(ta, file) : false;
  appendText(ta, text);
  ta.focus();
  return { file: gotFile, text: !!text };
}

// the input of the chat that is open now: the composer form with a textarea that is on the page; null while it is not there
export function openComposer(doc = document) {
  const forms = [...doc.querySelectorAll("form.composer")].filter((f) => f.querySelector("textarea") && f.getClientRects().length);
  return forms[forms.length - 1] || null;
}

// wait (up to `ms`) for the composer of the session chat that was just opened
export function waitComposer(ok, ms = 4000, doc = document) {
  return new Promise((done) => {
    const t0 = Date.now();
    (function tick() {
      const f = ok() ? openComposer(doc) : null;
      if (f) return done(f);
      if (!ok() || Date.now() - t0 > ms) return done(null);
      setTimeout(tick, 80);
    })();
  });
}
