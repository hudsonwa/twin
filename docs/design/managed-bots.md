# Design: a same-named Telegram bot per twin, through Telegram managed bots

Status: research and design (twin#67, spike for issues 05 and 06). Since 0.5.2 an opt-in prototype is in
`twin/tg_bots.py` (`telegram_bot_per_twin`, off by default, twin#68): it sends the request button; the `managed_bot`
update handler is tested against a fake transport only and is not yet called from Hermes' gateway (section 4 is
still the blocker). Nothing here was run against Telegram; every example name and id is invented.

Sources, read 2026-11-16: core.telegram.org/bots/api (current, Bot API 10.4), /bots/api-changelog, and
/bots/features ("Managed Bots"). Tags: **[doc]** = stated in the official docs; **[spike]** = not in the docs,
must be checked on a test account; **[ours]** = a design decision.

## 1. What the docs confirm

| Item | Finding | Tag |
|---|---|---|
| Introduced | Bot API 9.6, 3 Apr 2026: `User.can_manage_bots`, `KeyboardButtonRequestManagedBot` + `KeyboardButton.request_managed_bot`, `ManagedBotCreated` + `Message.managed_bot_created`, `ManagedBotUpdated` + `Update.managed_bot`, `getManagedBotToken`, `replaceManagedBotToken`, `t.me/newbot/...` links, Mini App `savePreparedKeyboardButton` | [doc] |
| Turning it on | Manager bot's settings in **BotFather's Mini App** -> enable "Bot Management Mode". Not a Bot API call. `getMe` then returns `can_manage_bots: true` (returned only in `getMe`) | [doc] |
| Request button | `KeyboardButton.request_managed_bot = {request_id: int32 (unique in the message), suggested_name?: str, suggested_username?: str}`. Username must end in `bot` (Premium owners may suggest `agent`/`ai`/`app`/`game` endings as a secondary username since 10.4; a `...bot` username is then assigned too). **Private chats only**; only for bots with management enabled. It is a reply-keyboard button (`KeyboardButton`), not an inline button | [doc] |
| Link | `https://t.me/newbot/{manager_bot_username}/{suggested_bot_username}[?name={suggested_bot_name}]` | [doc] |
| User control | The creation window has username and display name **pre-filled but editable** | [doc] |
| Result | Manager gets `Update.managed_bot` = `ManagedBotUpdated{user: User (creator), bot: User}`; with the button route also a `Message.managed_bot_created{bot: User}` service message | [doc] |
| Same update, later | `managed_bot` also fires when the managed bot's **token or owner changes** | [doc] |
| Token | `getManagedBotToken(user_id: int)` -> token string; `user_id` is the managed bot's id (`bot.id`) | [doc] |
| Rotate | `replaceManagedBotToken(user_id)` revokes and returns a new token | [doc] |
| Access (10.0, 8 May 2026) | `getManagedBotAccessSettings(user_id)` -> `BotAccessSettings{is_access_restricted, added_users?}`; `setManagedBotAccessSettings(user_id, is_access_restricted: bool, added_user_ids?: int[] up to 10)`. "The bot's owner can always access it." | [doc] |
| No zero-touch | No method creates a bot without a person confirming in their client | [doc] (absence) |

## 2. Still to verify on a test account (spike)

1. Whether `ManagedBotUpdated` carries anything tying it to our `request_id` (the docs show only `user` and `bot`).
   Design assumes it does not and correlates by creator + time window + pending request. [spike]
2. Whether `managed_bot_created` service message arrives in the owner's DM with the manager, and whether it
   carries the reply to our button message (would give a firm correlation). [spike]
3. How a token-change / owner-transfer `managed_bot` update can be told apart from a creation (same payload
   shape). Design: compare `bot.id` with what we already hold. [spike]
4. Whether `getManagedBotToken` keeps working after the owner transfers the bot away (expect: fails). [spike]
5. Does `is_access_restricted: true` make Telegram drop non-owner messages before they reach the bot (expect yes;
   our own allow-list stays anyway). [spike]
6. Can the manager delete a managed bot? No method is documented; assume no. [doc absence, spike]
7. **Hermes 0.22.7**: its Telegram adapter has no managed-bot code. Unknown whether its polling/webhook
   `allowed_updates` include `managed_bot`, and whether a plugin can see raw updates or send a reply-keyboard
   button. Likely needs a plugin-side hook or a short side poll; see section 4. [spike]
8. Hermes hot reconcile (`gateway/run_profile_reconcile.py`) adds the adapter when a profile `.env` gains a token
   *by `secrets.command`* (not only a literal `TELEGRAM_BOT_TOKEN=`). [spike]

## 3. Flow

One-time owner steps (cannot be automated):
- Have a Hermes gateway bot (already required by `hermes twin telegram on`; `NO_BOT` message names BotFather).
- In BotFather's Mini App, enable Bot Management Mode on that bot. The plugin checks `getMe.can_manage_bots`
  and, if false, FAILs with that exact instruction.

Per twin (one tap), `hermes twin telegram bot acme-support` or `telegram_bot_per_twin: on` after create:

1. Preflight (all FAIL closed, nothing sent): setting on; twin has safe defaults (`tg_route._unsafe`); gateway
   profile found (`tg_route.find_gateway`); exactly one owner id; host runs one multiplexing gateway, else FAIL
   naming `hermes gateway migrate`; OS secret store available (`secret_ref.store_reason()`), else FAIL (no plain
   `.env` fallback); `getMe.can_manage_bots` true.
2. Write a pending request to plugin state: `{twin, owner_id, request_id (random int32), suggested_username,
   created_at, expires_at = +15 min}`. No token fields exist in this record.
3. Send the owner's DM (chat id = owner id, private chat) one message with a one-button reply keyboard:
   `request_managed_bot = {request_id, suggested_name: "Acme Support", suggested_username: "acme_support_twin_bot"}`.
   Also print the equivalent link `https://t.me/newbot/<gateway_bot>/acme_support_twin_bot?name=Acme+Support`
   in the CLI, for the owner to open on the device they are on. Suggested username: twin id with `-` -> `_`,
   `_twin_bot` suffix, capped at 32 chars; Telegram may reject a taken name in its own UI and the owner edits it.
4. Owner taps, confirms (may edit name/username). Manager receives `managed_bot`.
5. Checks, in order, else ignore and log a reason without ids beyond the owner's:
   - `update.managed_bot.user.id == owner_id` (int compare).
   - A pending, unexpired request for this owner exists; exactly one (if several, the oldest is matched only
     when `managed_bot_created` replies to its message; otherwise refuse and ask the owner to re-run). [ours]
   - `bot.id` is not already mapped to another twin (that is a token/owner change, section 5).
   - Do **not** require the username to match the suggestion (docs: it is editable). Record the real one.
6. `getManagedBotToken(user_id=bot.id)` -> value goes straight to `secret_ref.keep("TWIN_TG_ACME_SUPPORT", value,
   kind="telegram", twin="acme-support")` and the local variable is dropped. Never logged, returned, or written to
   state; HTTP client logging for that call is silenced (the token is not in the URL of *this* call, but the
   manager's own token is in every Bot API URL, so the same rule already applies).
7. `setManagedBotAccessSettings(user_id=bot.id, is_access_restricted=true)` (owner-only at Telegram's edge).
8. Twin profile `.env`: `TELEGRAM_ALLOWED_USERS=<owner_id>` and the token by reference via `secrets.command`
   (a command that prints only that one value from the OS store). Note: today `secret_ref.write_env` writes the
   **value** into the twin's `.env`; issue 06 forbids that for this token, so a new reference-only writer is needed.
   Telegram turns on the twin: DM only, approvals denied, strict preset (same rules as `tg_route.guard`).
9. Host gateway hot-reconciles and starts polling the new bot. Plugin waits up to 60 s for the adapter to show
   up, then runs `hermes twin check-model acme-support` (IDEA section 3 step 5). PASS line names the twin and the
   bot's username, never the token.

Ownership note [doc]: the owner is the Telegram account that tapped, so the bot is theirs in BotFather; our
manager bot can also read its token. That is the trust trade-off of this route and is said in the PASS line once.

## 4. Where the update is received (open, decides the build)

Hermes owns the gateway bot's `getUpdates`/webhook; a second poller on the same token would steal updates.
Options, in preference order:
1. Hermes passes unknown update types to plugins (check its adapter's `allowed_updates` and handler). [spike]
2. Plugin registers a narrow Hermes hook if one exists for raw Telegram updates. [spike]
3. Fallback with no Hermes support: after sending the button, poll `getManagedBotAccessSettings` is not usable
   (needs the bot id). There is **no documented "list managed bots" call**, so without the update the plugin
   cannot learn the new bot id. Then the feature waits on Hermes, and the owner path stays manual: BotFather
   `/newbot` + `hermes twin secret set` + reference. Decision [ours]: do not run a competing poller.

## 5. Failure and fallback

| Case | Behaviour |
|---|---|
| Setting off | Nothing changes, no calls (tested) |
| `can_manage_bots` false | FAIL: "enable Bot Management Mode for @<bot> in BotFather's Mini App" |
| No OS secret store | FAIL before sending; no plain-`.env` fallback |
| Per-profile gateways | FAIL naming `hermes gateway migrate`; gateway untouched |
| Owner never taps | Pending request expires (15 min); `status` shows it; re-run sends a new button |
| Creator id is not the owner | Ignore, no reply, no token call; one log line "managed_bot from non-owner ignored" |
| Update with no pending request / unknown `bot.id` | Ignore (could be a bot the owner made through another link) |
| Known `bot.id` again (token change/owner change) | Re-fetch token into the same secret name; if `getManagedBotToken` fails (ownership moved), turn the twin's Telegram off and tell the owner |
| `getManagedBotToken` error | FAIL with Telegram's error description (no token in it); pending kept for one retry |
| Hot reconcile does not pick it up in 60 s | WARN, name `hermes gateway restart` as the owner's choice; do not restart |
| `stop TWIN` | Remove the reference from the profile, `secret_ref.forget` the name, optionally `replaceManagedBotToken` to kill any copy; suggest deleting the bot in BotFather (not done) |
| Leak suspicion | `hermes twin telegram bot TWIN --rotate` -> `replaceManagedBotToken` -> store |

## 6. Tests to write with the build (no network)

- Fake Bot API transport: assert the button payload shape, `request_id` int32, private chat only.
- `managed_bot` from non-owner, from owner without pending request, expired request, duplicate pending -> no
  token call, no reply.
- Token sentinel value (`123456:TEST-not-a-token-sentinel`) never appears in logs, state files, transcripts,
  event stream, model context, exception text or any `.env` (grep every written file).
- Group, channel, and non-owner DM to the new bot get no reply.
- Setting off: zero Bot API calls.

## 7. Spike plan (a person with a test account, later)

1. Test Telegram account + a fresh test manager bot (e.g. `@acme_test_manager_bot`); enable Bot Management Mode
   in the BotFather Mini App; record `getMe` before/after.
2. With a throwaway script (not Hermes) on `getUpdates` with `allowed_updates=["message","managed_bot"]`, send
   the button to the test account's DM; tap; record the raw update(s) and any `managed_bot_created` message
   with tokens redacted. Repeat with the link form and with an edited username.
3. Call `getManagedBotToken`, `set/getManagedBotAccessSettings`; message the new bot from a second test account
   with restriction on/off; call `replaceManagedBotToken` and record the follow-up `managed_bot` update.
4. Point a Hermes 0.22.7 test host at the manager bot: check whether the plugin can see `managed_bot`, send a
   reply-keyboard button, and whether hot reconcile adds a profile whose token comes via `secrets.command`.
5. Write the recorded run into this file (section 2 items closed or reopened).

## 8. What still needs a person

- Making the first bot (BotFather `/newbot`) and enabling Bot Management Mode (BotFather Mini App).
- One tap (plus confirm) per twin bot.
- Deleting a twin's bot in Telegram.
- Running the spike on a test account.

## 9. Open questions

- Correlation of update to request (section 2 items 1-2).
- Hermes plugin access to raw updates and reply keyboards (section 4) — the main blocker.
- Should the gateway bot's owner id and the managed bot's owner differ ever (shared hosts)? Design says no.
- Trust: the manager bot can always read the twin bot's token. Acceptable since both are the owner's, but it
  means a compromised gateway token exposes every twin bot token too; rotation covers recovery.
