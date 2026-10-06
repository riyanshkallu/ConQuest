# Outsmart API contract

This file is the handoff point between the backend (Python/FastAPI, `backend/`) and the
frontend (HTML/CSS/JS, `frontend/`). **Change it only when both teammates agree**, and
update it in the same pull request as the code change.

- Base path: `/api`. The backend also serves `frontend/` at `/`, so the frontend can call
  `fetch("/api/...")` with no CORS setup.
- All requests and responses are JSON (`Content-Type: application/json`).
- Live docs you can click through: `/docs` on the running backend.
- **Mock mode** (`AI_PROVIDER=mock`): every endpoint works with the same shapes as below, but
  the AI replies are canned lines, with no API keys needed. The frontend can build against this from day one.

## Ground rules

1. **Nothing reveals scam vs. legit until the round ends.** During a round the API never
   returns `is_scam`, the character's tactic, green flags, or pressure. They appear only
   in the action/message response that ends the round and in `/result`.
2. **The frontend never decides outcomes.** It displays what the API returns.
3. **Only fictional data.** The player uses the ID card. If a message looks like real
   personal data (SSN, a real card number, a phone number not on the ID card), the API
   rejects it with `blocked: true` and the message is never sent to the AI or saved.
4. **One request per round at a time.** While a message or action is being processed,
   another request for the same round gets `409 round_busy`. Disable the send and action
   buttons until the response arrives.

## Common shapes

### Error

Every non-2xx response has this body:

```json
{ "error": { "code": "round_not_found", "message": "No round with that id." } }
```

| HTTP | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Missing/wrong fields, empty message, message over 500 characters |
| 404 | `player_not_found`, `round_not_found`, `scenario_not_found` | Unknown id |
| 409 | `round_busy` | Another request for this round is still running |
| 409 | `round_ended` | Message/action sent after the round ended |
| 409 | `round_not_ended` | `/result` requested before the round ended |
| 500 | `server_error` | Bug on our side. Show "Something went wrong, try again." |

### Message

Used for the opening message, every reply, and notifications.

```json
{
  "sender": "contact",
  "text": "Buckeye Federal Fraud Alert: Did you attempt a $486.20 purchase at TechZone Online? Reply YES or NO.",
  "links": []
}
```

- `sender`: `"contact"` (the scammer or legit contact), `"player"`, or `"notification"`
  (a system text, such as the one-time code arriving from the real bank).
- `links`: every link in `text`, already extracted, e.g. `["secure-verify-account.example/login"]`.
  All links use the fake `.example` domain. Make them tappable. When the player taps one, call the
  action endpoint with `open_link` (see below), then show a simple "fake website" screen.

### Ending

```json
{ "code": "ESCAPED", "title": "Escaped", "message": "You made some mistakes but protected yourself in the end.", "is_scam": true }
```

| `code` | Round type | Title |
| --- | --- | --- |
| `OUTSMARTED` | scam | Outsmarted |
| `ESCAPED` | scam | Escaped |
| `ALMOST_SCAMMED` | scam | Almost Scammed |
| `SCAMMED` | scam | Scammed |
| `SMART_AND_SAFE` | legit | Smart and Safe |
| `LUCKY` | legit | Lucky |
| `FALSE_ALARM` | legit | False Alarm |

### Flags

Red flags (scam tactics) and green flags (signs of a real contact) use these ids everywhere:

- Red: `authority`, `urgency`, `fear`, `emotional_manipulation`, `fake_reward`,
  `trust_building`, `financial_pressure`, `suspicious_link`, `credential_request`,
  `platform_switch`, `secrecy`, `unusual_payment`
- Green: `invites_verification`, `no_credentials_asked`, `no_pressure`, `official_channels`,
  `checkable_details`, `accepts_no`, `no_secrecy`, `normal_payment`

Wherever a flag is returned, the backend returns it as a full object so the frontend never
needs its own copy of the labels:

```json
{ "id": "credential_request", "kind": "red", "label": "Credential request", "explanation": "Asking for a one-time code is a credential request. Real banks never ask for these." }
```

---

## Endpoints

### `POST /api/player`

Creates an anonymous player. Store `player_id` in `localStorage`.

Request (all fields optional):

```json
{ "display_name": "Riya" }
```

Response `201`:

```json
{
  "player_id": "p_7f3c9a1e2b4d",
  "display_name": "Riya",
  "settings": { "hints": false, "save_conversations": true }
}
```

### `PATCH /api/player/{player_id}/settings` *(proposed addition)*

The Settings screen needs somewhere to save the two settings the backend uses. Large text
is frontend-only, so keep it in `localStorage`. Send only the fields that changed. The
response returns the full settings.

```json
{ "hints": true }
```

Response `200`: `{ "hints": true, "save_conversations": true }`

### `POST /api/player/{player_id}/reset` *(proposed addition)*

Resets XP, level, streak, badges and Scam Radar. Response `200`: the same body as `GET /radar`.

### `GET /api/scenarios?player_id=...`

Response `200`:

```json
{
  "scenarios": [
    { "id": "bank_alert", "title": "Bank fraud alert", "channel": "sms", "difficulty": 2 }
  ],
  "train_your_weakness": {
    "scenario_id": "bank_alert",
    "category": "urgency",
    "label": "Urgency & fear",
    "percent": 54
  }
}
```

- `channel`: `"sms"`, `"dm"`, `"email"` or `"chat"`. Use it to style the chat screen.
- `train_your_weakness` is `null` until the player has finished at least one round.
- Each scenario id is a *pair* (scam version and legit version). The server picks which
  version the player gets when the round starts.

### `POST /api/round/start`

Request:

```json
{ "player_id": "p_7f3c9a1e2b4d", "scenario_id": "bank_alert" }
```

Response `201`:

```json
{
  "round_id": "r_91d0c2aa5e17",
  "scenario_id": "bank_alert",
  "channel": "sms",
  "difficulty": 2,
  "max_turns": 10,
  "contact": { "name": "Buckeye Federal", "handle": "72614" },
  "id_card": {
    "name": "Jordan Rivera",
    "email": "jordan.rivera@mail.example",
    "phone": "(555) 010-3382",
    "bank": "Buckeye Federal Credit Union",
    "card_number": "4000 0037 1822 4417",
    "card_last4": "4417",
    "password": null,
    "gift_card": null,
    "gaming_account": null,
    "family": null,
    "extras": []
  },
  "opening_message": { "sender": "contact", "text": "...", "links": [] },
  "suggested_replies": ["Who is this?", "YES", "I'll call the number on my card."]
}
```

- `id_card.gift_card` (when present): `{ "store": "PlayMart", "amount": 200, "code": "PMRT-7Q4K-22XD" }`.
- `id_card.gaming_account` (when present): `{ "game": "Blockcraft", "username": "jordan_builds" }`.
- `id_card.family` (family emergency scenario; proposed, see decision 7): what the player knows
  about their family, so they can check who's really texting:
  `{ "relative": "Alex (your cousin)", "parent": "Aunt Dana (Alex's mom)", "parent_phone": "(614) 555-0133",
  "memory_question": "Name of Grandma's dog", "memory_answer": "Biscuit" }`.
- `id_card.extras` (proposed, see decision 8): extra lines for a scenario, shown as more ID card rows
  in order. Example (tech support): `[{ "label": "Your open support ticket", "value": "#48213: laptop won't charge" }]`.
  Usually empty. Show them like the other rows.
- The one-time verification code is **not** on the ID card. It arrives mid-game as a
  `notification` message (see below), like a real text from the bank.

### `POST /api/round/{round_id}/message`

Request:

```json
{ "text": "How do I know this is really my bank?" }
```

`text` must be 1–500 characters after trimming.

Response `200` (round continues):

```json
{
  "blocked": false,
  "blocked_reason": null,
  "turn": 3,
  "max_turns": 10,
  "reply": { "sender": "contact", "text": "...", "links": [] },
  "notifications": [
    { "sender": "notification", "text": "Buckeye Federal: Your one-time code is 482913. We will never ask you for this code.", "links": [] }
  ],
  "suggested_replies": ["...", "...", "..."],
  "hint": { "suspicion": 55 },
  "ended": false,
  "ending": null
}
```

- `notifications`: show these **after** `reply`, as separate system bubbles. Usually empty.
- `hint`: `null` unless the player turned hints on. `suspicion` is 0–100, meaning how
  cautious the player is being.
- Show a typing indicator while waiting. The target is under 4 seconds.

Response `200` (blocked, which does not count as a turn):

```json
{
  "blocked": true,
  "blocked_reason": "That looks like a real Social Security number. Only use details from your ID card.",
  "turn": 2, "max_turns": 10, "reply": null, "notifications": [], "suggested_replies": [],
  "hint": null, "ended": false, "ending": null
}
```

Response `200` (the round just ended): `ended: true`, `ending` is set, and `reply` may be
`null`. Go to the reveal screen and call `/result`.

### `POST /api/round/{round_id}/action`

Request:

```json
{ "action": "verify" }
```

For `open_link`, also send the link: `{ "action": "open_link", "link": "secure-verify-account.example/login" }`.

| `action` | Button label | Ends round? | Notes |
| --- | --- | --- | --- |
| `verify` | Verify independently | yes | Response includes `verification_call` to show before the reveal |
| `hang_up` | Hang up / Block | yes | |
| `report` | Report as scam | yes | |
| `trust` | It's legit *(proposed addition)* | yes | The player decides the contact is real |
| `ask_proof` | Ask for proof | no | Counts as a player turn. The canned question is returned in `player_message` |
| `open_link` | *(tapping a link)* | no | Does not count as a turn. No reply |

Response `200`: the same shape as the message response, plus two fields:

```json
{
  "blocked": false, "blocked_reason": null, "turn": 4, "max_turns": 10,
  "player_message": null,
  "reply": null, "notifications": [], "suggested_replies": [], "hint": null,
  "verification_call": {
    "title": "Calling Buckeye Federal (number on the back of your card)",
    "official_name": "Buckeye Federal",
    "lines": [
      { "speaker": "official", "text": "Thanks for calling Buckeye Federal. How can I help?" },
      { "speaker": "player", "text": "I got a text saying my card was used for a $486 purchase." },
      { "speaker": "official", "text": "I don't see any fraud alert or pending purchase on your account. That text did not come from us." }
    ]
  },
  "ended": true,
  "ending": { "code": "OUTSMARTED", "title": "Outsmarted", "message": "...", "is_scam": true }
}
```

- `player_message`: for `ask_proof`, the question the player "sent". Show it as a player bubble, then the `reply`.
- `verification_call`: only for `verify`, otherwise `null`. `speaker` is `"official"` (whoever the
  player called: the bank, the store, a family member) or `"player"`. Show `official_name` as the
  official's name, e.g. "Aunt Dana: Hi sweetie!".

### `GET /api/round/{round_id}/result`

Only after the round ended (otherwise `409 round_not_ended`).

```json
{
  "round_id": "r_91d0c2aa5e17",
  "scenario_id": "bank_alert",
  "ending": { "code": "ESCAPED", "title": "Escaped", "message": "...", "is_scam": true },
  "biggest_clue": "They asked for your one-time code. Real banks never ask for it.",
  "points": 45,
  "points_breakdown": [
    { "label": "Verified independently", "points": 30 },
    { "label": "Spotted: Urgency", "points": 10 },
    { "label": "Shared your email", "points": -10 }
  ],
  "xp_earned": 65,
  "explanation": {
    "type": "scam_autopsy",
    "timeline": [
      {
        "turn": 1,
        "flag": { "id": "authority", "kind": "red", "label": "Authority", "explanation": "..." },
        "summary": "They pretended to be your bank's fraud team.",
        "player_response": "resisted"
      }
    ],
    "good_decisions": ["You asked how to know it was really your bank."],
    "mistakes": ["You shared your email address."],
    "best_decision": "You checked with the bank using the number on your card.",
    "biggest_weakness": { "category": "urgency", "label": "Urgency & fear" },
    "scam_twin": null
  },
  "transcript": [
    {
      "index": 0, "turn": 0, "sender": "contact", "text": "...",
      "flag": { "id": "authority", "kind": "red", "label": "Authority", "explanation": "..." },
      "note": null
    },
    {
      "index": 1, "turn": 1, "sender": "player", "text": "who is this",
      "flag": null,
      "note": "Good question. You asked who was really contacting you."
    }
  ],
  "tip": { "id": "urgency_pause", "text": "Real deadlines survive a 5-minute pause. If someone says you can't wait to check, that's the reason to check." },
  "new_badges": [ { "id": "first_escape", "name": "First Escape", "description": "..." } ]
}
```

- `explanation.type`: `"scam_autopsy"` or `"legit_breakdown"`.
- `timeline[].player_response`: in scam rounds `"resisted"`, `"fell_for_it"` or `"no_response"`.
  In legit rounds, `"noticed"` or `"missed"`.
- `scam_twin` (only after `LUCKY`): the matching scam version's key message, to show side by side:
  `{ "contact_name": "Buckeye Federal Fraud Team", "text": "..." }`.
- `transcript[].flag` is on contact messages. `note` is on player messages (what that reply did),
  and, with live AI, also on flagged contact messages (what that specific message was doing).
  Every message in the transcript is tappable: show the flag and the note when there is one.
- With live AI, `timeline[].summary` and the contact notes are written by the Explainer about
  this conversation. Without AI they're the generic flag explanations. The shape is the same
  either way, and the ending, points, responses and best decision are always decided by the engine.

### `GET /api/player/{player_id}/radar`

```json
{
  "player_id": "p_7f3c9a1e2b4d",
  "display_name": "Riya",
  "level": 3,
  "xp": 420,
  "xp_for_next_level": 600,
  "streak_days": 2,
  "radar": [
    { "category": "links_logins", "label": "Suspicious links & logins", "encountered": 12, "resisted": 11, "percent": 92 },
    { "category": "urgency", "label": "Urgency & fear", "encountered": 9, "resisted": 7, "percent": 78 },
    { "category": "impersonation", "label": "Impersonation", "encountered": 13, "resisted": 8, "percent": 61 },
    { "category": "financial", "label": "Money & rewards", "encountered": 7, "resisted": 6, "percent": 85 },
    { "category": "emotional", "label": "Emotional manipulation", "encountered": 11, "resisted": 6, "percent": 54 },
    { "category": "real_contacts", "label": "Recognizing real contacts", "encountered": 10, "resisted": 7, "percent": 70 }
  ],
  "badges": [
    { "id": "first_escape", "name": "First Escape", "description": "Finish a scam round without getting scammed.", "earned": true }
  ]
}
```

- Always six radar rows in this order. `percent` is `null` when `encountered` is 0.

---

## Decisions to confirm

These fill gaps in the plan doc. **Backend: agreed to all six (Sep 30). Frontend: waiting for your
yes/no on each.** Once you agree, change "waiting" to "agreed" here. The backend already works
this way.

| # | Decision | Backend | Frontend |
| --- | --- | --- | --- |
| 1 | `trust` action / "It's legit" button | agreed | waiting |
| 2 | Finishing a legit contact's request ends the round | agreed | waiting |
| 3 | Clean hang-up: OUTSMARTED only if a trick was called out | agreed | waiting |
| 4 | `open_link` action for tapped links | agreed | waiting |
| 5 | One-time code arrives in both scam and legit rounds | agreed | waiting |
| 6 | Settings and reset endpoints | agreed | waiting |
| 7 | `id_card.family` and `verification_call.official_name` | agreed | waiting |
| 8 | `id_card.extras` for scenario-specific ID card lines | agreed | waiting |

1. **`trust` action ("It's legit").** The plan had no way to say "I believe you," so the
   LUCKY and SMART AND SAFE endings had no clear trigger. In a legit round, `trust` gives
   SMART_AND_SAFE if the player named a real green flag during the chat and shared nothing
   sensitive, and LUCKY otherwise. In a scam round, it gives SCAMMED.
2. **Finishing the legit contact's request ends the round.** For example, the player replies "NO"
   to confirm a charge with the real bank. That ends the round like `trust` does, so a legit round
   can't end in an awkward FALSE_ALARM just because the player hangs up after the conversation is over.
3. **Clean hang-up in a scam round.** OUTSMARTED needs zero mistakes, nothing shared, and at
   least one scam tactic the player called out. Otherwise the ending is ESCAPED. A clean
   ESCAPED gets its own message ("You got out safely…"), so always show `ending.message`
   from the API instead of hard-coding the text for each ending.
4. **Links** are reported with the `open_link` action. Risk +25, not a turn.
5. **The one-time code** arrives as a `notification` on a set turn in *both* scam and legit
   rounds, so its arrival doesn't give away which kind of round it is.
6. **Settings and reset endpoints** (above) were added for the Settings screen.
7. **Family details and who you called** (added with the job and family scenarios). The family
   emergency scenario needs the player to know a family detail ("What's Grandma's dog's name?") and
   a parent's number to call, so the ID card gets an optional `family` section. Verify calls are no
   longer always "the bank", so call lines use `speaker: "official"` plus `official_name`.
   `index.html` already shows both.
8. **Scenario-specific ID card lines** (added with the gaming and tech support scenarios). Some
   clues only make sense on one scenario's ID card: your friend's real handle (the scam uses a
   lookalike) or your open support ticket number (the real agent knows it, the scammer doesn't).
   Rather than a new field per scenario, the ID card gets a generic `extras` list of label/value
   rows. `index.html` already shows them, and has two new scenario cards for the new scenarios.

### Still open

- **Family Player badge.** The plan awards it for "a second profile on the same device," but
  only the browser knows about other profiles. Idea: when creating a player, the frontend sends
  the ids already saved in `localStorage`, for example
  `POST /api/player {"display_name": "Grandpa", "other_player_ids": ["p_7f3c9a1e2b4d"]}`.
  Not built yet. Discuss at the Oct 4 integration day.
