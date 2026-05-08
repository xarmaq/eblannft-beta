# eblanNFT — Knowledge Base for AI Agents

> Read this **before** modifying anything. The plugin has a lot of moving
> parts and intertwined hooks; mistakes break in subtle ways (silent UI
> regressions on remote profiles, lost cache state, ANRs) that you only
> notice when the user reports them.

## What this project is

`eblanNFT` is an Android plugin for **exteraGram** (a fork of Telegram for
Android). It lets users:

1. Visually inject NFT-style "Star Gifts" into their own profile
2. Spoof their NFT username and NFT phone number locally (visible to others
   via VPS sync — see below)
3. Wear a fake `emoji_status` collectible (the orbital ring around the avatar)
4. Decorate a fake "Stars Rating" widget on their profile
5. Sync all of the above to other users running the same plugin via a
   small VPS server (`http://35.242.218.223:8787`)

The plugin runs **inside** the Telegram client process via Chaquopy
(Python on Android). It hooks Java methods on Telegram's classes (mainly
`MessagesController`, `ProfileActivity`, `StarGiftSheet`, `UserConfig`,
`NotificationCenter`) using the exteraGram plugin API
(`base_plugin.MethodHook`).

There are **two repos** that ship the same codebase with different
package names:

| Repo | Package | URL |
|---|---|---|
| Production | `eblannft` / `eblannft_runtime` | https://github.com/xarmaq/eblannft |
| Beta | `eblannft_beta` / `eblannft_beta_runtime` | https://github.com/xarmaq/eblannft-beta |

Local working copies live at:
- Prod: `D:\vcNFT\_beta_work\main\`
- Beta: `D:\vcNFT\_beta_work\upstream\`

Both have git remotes pre-configured with PATs that allow push.

## Repository layout

```
<repo>/
├── eblannft.plugin             ← Bootstrap loader. Has the auto-update
│                                  popup, settings UI for update interval,
│                                  GitHub manifest fetcher.
├── eblannft_update.json        ← Manifest: { version, notes, files }.
│                                  Bumped on every release; bootstrap
│                                  reads it via raw.githubusercontent.com.
├── eblannft_runtime/           ← (or eblannft_beta_runtime/ in beta)
│   ├── __init__.py             ← Empty marker file.
│   ├── plugin.py               ← THE main plugin. ~30k lines. Single
│   │                              giant class `EblanNftPlugin` /
│   │                              `NftClonerPlugin` plus helper hook
│   │                              classes at the bottom.
│   └── sync_client.py          ← VPS sync background HTTP client
│                                  (push 12s / pull 6s / cache 4s).
└── KNOWLEDGE.md                ← This file.
```

The bootstrap (`eblannft.plugin`) is the user-installed file. On first
load it downloads the runtime files from GitHub raw URLs into the device
filesystem and `importlib`-loads them. On every load it polls
`eblannft_update.json` and shows an MD3 BottomSheet popup if the remote
version differs.

## Telegram source location

Read-only Telegram client source for reference is at:
```
D:\vcNFT\_tmp_telegram_src\TMessagesProj\src\main\java\
```

Always grep this when adding hooks — class names, method signatures and
field names must match exactly. Common files:
- `org/telegram/messenger/MessagesController.java` — user/chat cache, putUser/getUser
- `org/telegram/messenger/UserConfig.java` — current logged-in user
- `org/telegram/messenger/NotificationCenter.java` — UI refresh events
- `org/telegram/ui/ProfileActivity.java` — profile rendering
- `org/telegram/ui/Stars/StarGiftSheet.java` — gift detail bottom sheet
- `org/telegram/ui/Gifts/ProfileGiftsContainer.java` — gifts grid in profile
- `org/telegram/ui/Components/UniversalRecyclerView.java` — gift grid recycler
- `org/telegram/tgnet/TLRPC.java` — TL types (User, UserFull, TL_emojiStatusCollectible, etc.)

## Architectural pillars

### 1. Hook-driven Java method patching

Every plugin behaviour comes from hooking a Java method:

```python
class FooHook(MethodHook):
    def __init__(self, plugin):
        self.plugin = plugin
    def before_hooked_method(self, param):
        # mutate param.args[i] before Java sees them, OR call
        # param.setResult(x) to short-circuit and return x without
        # running the original method.
        ...
    def after_hooked_method(self, param):
        # mutate param.getResult() to override return value
        ...

# Wire it up — usually in some _hook_xxx setup method called from on_plugin_load.
java_class = jclass("org.telegram.messenger.MessagesController")
m = java_class.getDeclaredMethod("putUser", TLRPC$User, "boolean")
m.setAccessible(True)
self.hooks_refs.append(self.hook_method(m, FooHook(self)))
```

`self.hooks_refs` is a list of all hooks; cleaned up in `on_plugin_unload`.

### 2. Network request interception

The plugin hooks `ConnectionsManager.sendRequest(TLObject, RequestDelegate, int)`
in `NetworkHook.before_hooked_method`. There it inspects `req` (an
incoming TL request), classifies it by simple-name substring (`"gift"`,
`"emojistatus"`, `"getfulluser"`, etc.) and **wraps the original
RequestDelegate in `param.args[1]`** with a Python `RequestDelegate`
proxy (`WrapperDelegate`, `UserWrapperDelegate`, `StatusWrapperDelegate`,
`GiftLookupDelegate`, etc.).

When the response comes back, our wrapper runs first, can mutate the
response (or fake a successful one out of an error) and then forwards to
the original delegate.

### 3. Cache-write interception

`MessagesController.putUser` / `putUsers` are hooked to apply our
overrides **on the way in**, before the user object is stored in the
cache. This means even paths that don't go through `sendRequest` (e.g.
SQL storage load, processUpdates from long-polling) get patched.

`MessagesController.getUser` / `getUserFull` / `getUserOrChat` are also
hooked to re-apply on read — defensive in case some path mutated the
cached object in-place between writes. There's a short TTL skip cache
(`_should_skip_hot_get_override`) to avoid running reflection on every
single call, but it's bypassed when identity/wear is active.

`UserConfig.setCurrentUser` and `getCurrentUser` are similarly hooked
since the drawer/account-list reads from there directly.

### 4. NotificationCenter as the UI refresh trigger

After mutating the cache, the plugin posts events to NotificationCenter
to make Telegram repaint:
- `mainUserInfoChanged` → for self profile
- `userEmojiStatusUpdated(user)` → per-user fast path for wear status
- `updateInterfaces(mask)` → for any user; mask is bitwise OR of:
  - `UPDATE_MASK_NAME` = 2
  - `UPDATE_MASK_STATUS` = 4
  - `UPDATE_MASK_EMOJI_STATUS` = 524288
- `emojiLoaded` (global NC) → animated emoji drawables redraw

**CRITICAL**: when posting via `nc.postNotificationName(eid, *args)`,
integer args MUST be wrapped in `to_java_Integer()` (defined at the top
of plugin.py). Chaquopy autoboxes Python `int` as `java.lang.Long` in
`Object[]` varargs context, and `DialogsActivity.didReceivedNotification`
casts `args[0]` to `Integer` for `updateInterfaces` — `Long → Integer`
crashes the app. **DO NOT** use bare `to_java_int(eid)` for the second
positional arg of postNotificationName.

### 5. The `force=true` putUser issue

`MessagesController.putUser(user, fromCache)` early-returns when
`oldUser == user` (the in-place patch case — same object reference). It
never updates `objectsByUsernames`, never broadcasts. Always call the
3-arg overload: `ctrl.putUser(user_obj, False, True)` with fallback to
the 2-arg form for older Telegram builds:

```python
try:
    ctrl.putUser(user_obj, False, True)   # force=true
except Exception:
    ctrl.putUser(user_obj, False)
```

There are ~6 putUser sites in the codebase. **All wear/identity-related
ones use the force-true pattern.** If you add new ones, do the same.

## VPS sync

### Server

`http://35.242.218.223:8787` (also reachable as plain HTTP, no TLS yet).
REST-ish, JSON. Three endpoints:
- `GET /api/v1/users/<user_key>/state` → returns the snapshot for `tg:<uid>`
- `PUT /api/v1/users/<user_key>/state` → writes our snapshot
- `GET /health` → liveness

Auth header: `X-Plugin-Key: <hex>`. Hardcoded in `_sync_get_settings`.

The server doesn't filter by `plugin_id` so prod (`"eblannft"`) and beta
(`"eblannft_beta"`) records share the same `tg:<uid>` namespace —
clients on different builds **see each other**. This is intentional.

### Client (`sync_client.py`)

Two daemon threads: a push loop (12s) and a pull loop (consumes a queue
populated by `request_remote_state`, every 1s tick). Cache is a dict
keyed by `user_key`, with timestamps for freshness checks.

Tunable constants at the top:
```python
DEFAULT_PUSH_INTERVAL_SEC = 12
DEFAULT_PULL_INTERVAL_SEC = 6
STALE_CACHE_SEC = 4
```

**Don't raise these without thinking** — small values keep "live" feel
between two clients but multiply server traffic if the user base grows.

### Snapshot shape

Built by `_sync_collect_local_state` in plugin.py:

```json
{
  "plugin_id": "eblannft" | "eblannft_beta",
  "updated_at": <epoch>,
  "gifts": [
    {
      "b64": "<base64 TL_savedStarGift>",
      "title": "...", "slug": "...", "key": "...",
      "num": <int>, "base_gift_id": <int>, "unique_id": <int>,
      "saved_id": <int>, "order_hint": <int>,
      "inject": true, "pinned_override": true|false,
      "hidden_override": false,
      "wear_status_data": { ... },
      "build_config": { ... },
      "identity_config": { "owner_user_id": 0, "from_user_id": 0, "to_user_id": 0 },
      "value_config": { "amount": "5", "currency": "USD" },
      "gift_stars_config": { "amount": 1000 },
      "ton_display_config": { "enabled": false, ... }
    }
  ],
  "wear_active": true,
  "wear_collectible_id": <long>,
  "wear_status_data": { "collectible_id": ..., "center_color": ..., ... 8 fields },
  "username_state": { "enabled": true, "tokens": ["..."], "price_ton": "...", ... },
  "number_state": { "enabled": true, "tokens": ["+8881234567"], ... },
  "rating_state": { "enabled": true, "value": 50000, "level": 5, "next_goal": 100000 }
}
```

### Receiver-side flow

When the user opens a foreign profile, `NetworkHook` wraps:
- `getSavedStarGifts` → `WrapperDelegate` → `process_response` checks if
  the request is for a non-self user, then `_sync_inject_remote_gifts`
  pulls the cached snapshot, deserializes b64 wrappers, applies all the
  meta (owner_id, value_config, gift_stars_config, ton_display_config,
  identity_config, pinned/hidden/order_hint), then **two-phase inserts**
  pinned ones above the fold and normal ones at the end.
- `getFullUser` / `getUsers` → `UserWrapperDelegate` →
  `_sync_apply_remote_user_overrides` walks the response and patches
  `emoji_status`, `usernames`, `phone`, `stars_rating`, `stargifts_count`
  on UserFull-shaped objects.

In parallel, `_sync_patch_remote_cached_user` patches the same fields on
the closer-to-UI cached User in `MessagesController` (with `putUser(...,
True)` for force, plus `_post_remote_profile_notifications` for refresh).

### Critical: don't write `from_id` on remote synced gifts

[StarGiftSheet.java:8374](D:\vcNFT\_tmp_telegram_src\TMessagesProj\src\main\java\org\telegram\ui\Stars\StarGiftSheet.java#L8374)
shows the "**X** sent you this gift on **Y**" header whenever
`gift.from_id != null`, with no check on whether the viewer is actually
the recipient. So setting `from_id` on a foreign profile's gift makes it
look like the foreign user gifted YOU the gift, which is wrong.

`_sync_inject_remote_gifts` explicitly **clears** `from_id`,
`saved_from_id`, `sender_id` and the `flags & 2` bit on every wrapper
after deserialize. Only `owner_id` is set. **DO NOT** propagate
`from_id`/`to_id` from snapshot — only `owner_user_id` is safe.

### Foreign profile gifts tab visibility

Telegram's `ProfileActivity:10392` checks
`userInfo.stargifts_count > 0` before creating the «Подарки» tab. For
profiles with zero real gifts, our sync injection is invisible because
the tab doesn't exist. Fix: `_apply_remote_stargifts_count_to_obj` bumps
the count to `max(current, len(synced_gifts))` on UserFull-shaped objects
during both sync paths.

## Common gotchas

### TL field reflection

Most TL classes are plain Java POJOs with public fields. Use:
```python
self._set_field(obj, "field_name", value)   # tries declared fields, walks superclass chain
get_val(obj, "field_name", default=None)   # safe getter
```

Field types matter. `Peer` fields like `from_id` accept `TL_peerUser` or
similar; `int` fields accept Python int; `String` fields accept `str`.
**Writing `None` to a Peer field works (clears it)**; writing `None` to
a primitive int will throw.

`TLRPC$User` does NOT have an `emoji_status` field on its direct class
in some Telegram builds — it's on `TLRPC$TL_userFull`. Some helpers walk
nested `user` references inside UserFull. Be defensive.

### Chaquopy boxing pitfalls

- Python `int` → Java `Long` in Object[] varargs. Use `to_java_Integer(x)`
  if the receiver expects `Integer` (notably postNotificationName masks).
- `to_java_int(x)` returns a Python int normalised to Java int range. Use
  it for the **int parameter slots** (eid, account, etc.) but NOT for
  varargs receivers that cast to Integer.
- `dynamic_proxy(JavaInterface)` to implement Java interfaces in Python.
  Use it for `Runnable`, `RequestDelegate`, etc. Don't recreate the class
  on every call — reuse instances when possible.
- `jclass("foo.Bar")(...)` instantiates a Java class with the no-arg
  constructor (or matched constructor by arg types).

### Threading model

- All Java callbacks (hook methods) run on whatever thread Telegram
  invoked them on. Many fire on a background thread.
- UI mutations (setText, setVisibility, animate, etc.) MUST be on the UI
  thread. Use `run_on_ui_thread(callable)` (imported from `android_utils`)
  or `AndroidUtilities.runOnUIThread(JRunnable, delay_ms)`.
- Background threads are spawned freely with
  `threading.Thread(target=fn, daemon=True).start()`. Always daemon so
  they die with the process — no explicit cleanup needed.

### Persistence

- `gift_library` is the user's collection of NFT entries (each is a
  Python dict with `b64`, configs, flags, etc.). Persisted to a JSON file
  in the plugin's data dir. Saved via `_save_cache` (debounced).
- `injection.bin` is the legacy single-payload TL serialization. Mostly
  unused — `injection_payloads[]` (built from `gift_library`) is the
  active list.
- `wear_status_data` is a dict of the 8 visual fields needed for
  `TL_emojiStatusCollectible` (see "Поле emoji_status" below). Sticky in
  memory and persisted with the library entry.
- Don't access `gift_library` etc. without `try/except` on real device —
  serialization issues can leave entries in inconsistent shapes.

### `Поле emoji_status` (8 required fields)

`TL_emojiStatusCollectible` requires ALL 8 visual fields populated for
ProfileActivity to render the orbit:
- `collectible_id` (long) — gift unique id
- `center_color`, `edge_color`, `pattern_color`, `text_color` (int RGB24)
- `document_id` (long) — model emoji
- `pattern_document_id` (long) — pattern emoji
- `title` (string) — collectible name
- `slug` (string) — for deeplinks

If any are zero/empty, ProfileActivity treats the status as invalid and
reverts to plain emoji status. `_build_collectible_status_from_wsd`
populates all 8 from the per-gift `wear_status_data` dict.

### Force=true everywhere for putUser

Recap: in any new code that mutates a cached User object in-place and
needs UI refresh, use the 3-arg force-true pattern. There's no exception.

### Update popup percent / progress bar

The popup uses a single-thread tween for percent text (avoids the
"19→21→20" flicker from racing per-callback tweens) and a dual-method
fill bar (`setScaleX` + `LayoutParams.width` fallback) because
`ViewPropertyAnimator.scaleX` silently no-ops on some MIUI/Honor builds
when starting from `scaleX=0`. Don't revert to `animate().scaleX().start()`
without verifying it works on those skins.

## Release process

The user manually downloads the bootstrap `.plugin` from
`https://raw.githubusercontent.com/xarmaq/<repo>/main/eblannft.plugin`
and the bootstrap auto-pulls the runtime files from the same raw URLs.
So **every push to `main` is effectively a release**.

When making a release:

1. **Edit code** — make the actual changes in `eblannft_runtime/plugin.py`
   (or `eblannft_beta_runtime/plugin.py` in beta) and possibly other
   files. Mirror to both repos when the change applies to both.
2. **Validate syntax**: `python -c "import ast; ast.parse(open('<path>', encoding='utf-8').read()); print('OK')"`
   for each modified `.py`/`.plugin`. Plugin file is also Python syntax
   under the bootstrap `.plugin` extension.
3. **Bump version in 3 places** (per repo):
   - `eblannft.plugin` — `__version__ = "X.Y.Z"`
   - `eblannft_runtime/plugin.py` — `__version__ = "X.Y.Z"`
   - `eblannft_update.json` — `"version": "X.Y.Z"` AND update `"notes"`
4. **Notes format**: short Russian text; if you have multiple distinct
   changes, use `(1) ... (2) ... (3) ...` numbered groups — the popup's
   `_parse_notes_bullets` will render each as a separate bullet row in
   the «Что нового» card. Strip the leading `vX.Y.Z — ` prefix from
   bullets automatically.
5. **Manifest `files` list** — must include every runtime file that needs
   to be downloaded. Currently: `eblannft.plugin`,
   `eblannft_runtime/__init__.py`, `eblannft_runtime/plugin.py`,
   `eblannft_runtime/sync_client.py`. Bootstrap won't fetch what's not
   listed.
6. **Commit + tag + push** (both repos if applicable):
   ```
   git -c user.email="bot@local" -c user.name="eblannft-bot" commit -am "vX.Y.Z — short summary"
   git tag -f vX.Y.Z
   git push
   git push --tags --force
   git log --oneline -3   # verify push landed
   ```
7. **NEW files** require explicit `git add <path>` before the commit
   (since `commit -am` only stages tracked files). Verify with
   `git status` after commit that no untracked files remain.

### Cross-repo discipline

Most changes apply to both prod and beta. Make the edit in prod
(`D:\vcNFT\_beta_work\main\`), validate, then mirror the same edit
verbatim to beta (`D:\vcNFT\_beta_work\upstream\`). The two `.plugin`
bootstraps differ only in `__id__`, `__name__`, `__description__`,
`__version__`, `_RUNTIME_REPO`, `_RUNTIME_DIR_NAME`,
`_RUNTIME_PACKAGE_NAME`, `_RUNTIME_PACKAGE_ALIAS`. The popup code is
otherwise identical — `diff` regularly to verify. The runtime `plugin.py`
files also share most code; beta usually leads (sync_client lived only
in beta until prod 1.0.3).

Version sequences are independent: prod runs 1.0.x, beta runs 1.0.x with
its own counter. Don't try to keep them aligned — just bump each repo's
version when you push to it.

### What NOT to do

- **Don't `git push --force` to `main`.** Use `--tags --force` only on
  tags after retagging.
- **Don't skip pre-commit hooks** (`--no-verify` etc.). If a hook fails,
  fix the underlying issue.
- **Don't commit secrets.** The hardcoded `plugin_key` for VPS sync is
  not really secret (it's shipped in the plugin), but anything else
  obviously sensitive should not land in repo.
- **Don't refactor for refactor's sake.** The codebase has a lot of
  defensive `try/except` wrappers, length, weird comments — most of it
  is there because something subtle broke once. Leave it unless
  you understand WHY.
- **Don't change the snapshot format incompatibly.** Other clients on
  older versions are reading the same record. Only ADD optional keys.
- **Don't remove `try/except` around field reflection.** Telegram TL
  field names sometimes get added/removed across builds. The defensive
  wrappers let the plugin keep working on a wider range of client
  versions.

## Testing on device

The user installs/reinstalls the plugin manually by downloading the
bootstrap `.plugin` URL. After your push, they download the new file,
disable the old plugin (or replace it), enable. The bootstrap then
auto-pulls runtime updates.

**`logcat | grep NFT_ARCH`** is the primary diagnostic channel. Most
hooks log into this tag with prefixes like `>>> Hooking USER:`,
`Remote sync inject for uid=...: +N`, `STEAL MODE:`, `WEAR SAVED:`,
`Faked success`, `emoji_status set`. When you ship a new feature, add
log markers around the entry/exit points so the user can verify by
filter.

`[NFT_SYNC]` is the secondary tag for VPS sync events (push/pull,
HTTP errors).

If the user reports a bug, ask for a fresh `logcat` excerpt with both
filters. Don't guess.

## Useful greps

```bash
# Find a hook installer
grep -n "def _hook_" eblannft_runtime/plugin.py

# Find all putUser sites (verify force-true pattern)
grep -n "ctrl.putUser\b" eblannft_runtime/plugin.py

# Find sync touchpoints
grep -n "_sync_\|_eblannft_sync_" eblannft_runtime/plugin.py

# Find the right Telegram source file for a method
grep -rln "MethodNameHere" D:/vcNFT/_tmp_telegram_src/TMessagesProj/src/main/java
```

## Final note

When in doubt, look at how a similar feature was already wired up. The
codebase has near-templates for: hooking a method, wrapping a
RequestDelegate, applying a profile override, posting NC notifications,
serialize/deserialize a TL object via base64, scheduling delayed UI
batches with a key (`_schedule_ui_batch` / `_schedule_cached_user_patch`
with deduping). Reuse the patterns instead of inventing new ones.
