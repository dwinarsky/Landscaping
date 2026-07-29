/* Entry point: unlock if the build is encrypted, then start the map.
 *
 * Three cases, all handled here so nothing downstream cares:
 *   - single-file bundle: the data is already inlined, start immediately
 *   - encrypted deploy:   ask for the passphrase, decrypt, then start
 *   - local development:  no auth.json, files are read straight off disk
 */

async function start() {
  // encrypt_site.py stamps this meta tag into the locked build. Checking for
  // it beats probing for auth.json, which 404s noisily on a plaintext build.
  const locked = document.querySelector('meta[name="plan-locked"]');
  if (!window.__PLAN_DATA__ && locked) {
    const { unlock } = await import("./lock.js");
    await unlock(locked.content || "auth.json");
  }
  await import("./app.js");
}

start().catch((err) => {
  console.error(err);
  document.body.insertAdjacentHTML("afterbegin",
    `<p style="position:fixed;inset:auto 12px 12px;z-index:99;margin:0;padding:12px 14px;
       background:#fff;color:#8c2f20;border:1px solid #e0b9b1;border-radius:10px;
       font:14px/1.5 system-ui">Could not start the plan: ${err.message}</p>`);
});
