/* Passphrase gate for the deployed site.
 *
 * The private files are shipped as AES-GCM ciphertext (see
 * tools/encrypt_site.py). This asks for the passphrase, derives the key with
 * PBKDF2 via Web Crypto, and decrypts in the browser. Nothing readable ever
 * leaves the server, so this is real protection rather than a hidden UI - but
 * its strength is entirely the strength of the passphrase, because anyone can
 * download the ciphertext and grind at it offline.
 *
 * Decrypted bytes are handed to the app through the same window.__PLAN_DATA__
 * and window.__PLAN_ASSETS__ globals the single-file bundle uses, so nothing
 * downstream needs to know the site was ever locked.
 */

// Neutral name: this file is public on the locked deploy.
const KEY_CACHE = "plan-key";

const enc = new TextEncoder();
const dec = new TextDecoder();

const b64ToBytes = (s) =>
  Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const bytesToB64 = (b) =>
  btoa(String.fromCharCode(...new Uint8Array(b)));

async function deriveKey(passphrase, kdf) {
  const base = await crypto.subtle.importKey(
    "raw", enc.encode(passphrase), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: b64ToBytes(kdf.salt),
      iterations: kdf.iterations,
      hash: kdf.hash,
    },
    base,
    { name: "AES-GCM", length: 256 },
    true,                              // extractable, so it can be remembered
    ["decrypt"],
  );
}

/** Ciphertext files are iv || payload. */
async function decrypt(key, buf) {
  const bytes = new Uint8Array(buf);
  return crypto.subtle.decrypt(
    { name: "AES-GCM", iv: bytes.slice(0, 12) }, key, bytes.slice(12));
}

async function checkKey(key, manifest) {
  try {
    await decrypt(key, b64ToBytes(manifest.verifier).buffer);
    return true;
  } catch {
    return false;
  }
}

async function rememberKey(key) {
  const raw = await crypto.subtle.exportKey("raw", key);
  try { localStorage.setItem(KEY_CACHE, bytesToB64(raw)); } catch { /* private mode */ }
}

async function recallKey(manifest) {
  let stored;
  try { stored = localStorage.getItem(KEY_CACHE); } catch { return null; }
  if (!stored) return null;
  try {
    const key = await crypto.subtle.importKey(
      "raw", b64ToBytes(stored), { name: "AES-GCM" }, true, ["decrypt"]);
    return (await checkKey(key, manifest)) ? key : null;
  } catch {
    return null;
  }
}

export function forgetKey() {
  try { localStorage.removeItem(KEY_CACHE); } catch { /* ignore */ }
}

/** Decrypt every private file and expose it the way the app expects. */
async function loadEverything(key, manifest, onProgress) {
  const data = {};
  const assets = {};
  let done = 0;

  await Promise.all(manifest.files.map(async (path) => {
    const res = await fetch(`${path}.enc`, { cache: "force-cache" });
    if (!res.ok) throw new Error(`could not load ${path} (${res.status})`);
    const plain = await decrypt(key, await res.arrayBuffer());

    if (path.endsWith(".json")) {
      data[path] = JSON.parse(dec.decode(plain));
    } else {
      // Blob URLs let the existing <img src> paths work untouched.
      const type = path.endsWith(".webp") ? "image/webp" : "image/jpeg";
      assets[path] = URL.createObjectURL(new Blob([plain], { type }));
    }
    onProgress(++done, manifest.files.length);
  }));

  window.__PLAN_DATA__ = data;
  window.__PLAN_ASSETS__ = assets;
}

function gateMarkup() {
  return `
    <form class="lock-card" id="lock-form">
      <svg class="lock-mark" viewBox="0 0 32 32" aria-hidden="true">
        <path d="M10 4h12l6 12-6 12H10L4 16z"/><path d="M5 16h22"/>
      </svg>
      <h1>Landscape Plan</h1>
      <p class="lock-sub">Locked &middot; enter the passphrase to view</p>
      <label class="lock-label" for="lock-pass">Passphrase</label>
      <input id="lock-pass" type="password" autocomplete="current-password"
             autocapitalize="off" autocorrect="off" spellcheck="false" required>
      <label class="lock-remember">
        <input type="checkbox" id="lock-remember" checked>
        Remember on this device
      </label>
      <button type="submit" class="lock-go">Unlock</button>
      <p class="lock-msg" id="lock-msg" role="status"></p>
    </form>`;
}

/**
 * Show the gate and resolve once the plan is decrypted and in place.
 * Only called when index.html carries the plan-locked marker.
 */
export async function unlock(manifestUrl = "auth.json") {
  const res = await fetch(manifestUrl, { cache: "no-cache" });
  if (!res.ok) throw new Error(`could not load ${manifestUrl} (${res.status})`);
  const manifest = await res.json();

  if (!crypto?.subtle) {
    throw new Error("This browser cannot decrypt the plan. "
      + "Web Crypto needs a secure connection - open the https:// address.");
  }

  const host = document.createElement("div");
  host.className = "lock";
  host.innerHTML = gateMarkup();
  document.body.append(host);

  const form = host.querySelector("#lock-form");
  const input = host.querySelector("#lock-pass");
  const msg = host.querySelector("#lock-msg");
  const go = host.querySelector(".lock-go");

  const finish = async (key) => {
    go.disabled = true;
    input.disabled = true;
    await loadEverything(key, manifest, (n, total) => {
      msg.textContent = `Decrypting the plan… ${n} of ${total}`;
      msg.className = "lock-msg";
    });
    host.classList.add("is-open");
    setTimeout(() => host.remove(), 400);
  };

  const remembered = await recallKey(manifest);
  if (remembered) {
    await finish(remembered);
    return true;
  }

  input.focus();

  await new Promise((resolve) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const pass = input.value;
      if (!pass) return;
      go.disabled = true;
      msg.textContent = "Checking…";
      msg.className = "lock-msg";

      let key;
      try {
        key = await deriveKey(pass, manifest.kdf);
      } catch (err) {
        msg.textContent = `Could not derive a key: ${err.message}`;
        msg.className = "lock-msg is-bad";
        go.disabled = false;
        return;
      }

      if (!(await checkKey(key, manifest))) {
        msg.textContent = "That passphrase does not open this plan.";
        msg.className = "lock-msg is-bad";
        go.disabled = false;
        input.select();
        return;
      }

      if (host.querySelector("#lock-remember").checked) await rememberKey(key);
      try {
        await finish(key);
        resolve();
      } catch (err) {
        msg.textContent = err.message;
        msg.className = "lock-msg is-bad";
        go.disabled = false;
        input.disabled = false;
      }
    });
  });

  return true;
}
