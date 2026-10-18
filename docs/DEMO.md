# Demo kit — live demo (3 min), video (2 min), Devpost

## Before you present (10 minutes ahead)

1. Sign in as **Maya** (`maya@runway.demo`) on the laptop, **Sam** (`sam@runway.demo`) on a phone.
2. Circles → **Reset demo** (bottom of the page, demo accounts only). Wait for "The demo is fresh" —
   about a minute. This rebuilds Maya, Jordan, Sam and Emma and **holds automatic help for an hour**, so
   the cover happens live when you tap it.
3. Check Maya's Today: *"You dip to $165 … before payday"* and Circles shows Sam, Jordan, Emma as ready.
4. Have the GitHub repo open on `backend/app/guardian.py` and `backend/evals/README.md` (Privacy eval).

## Live demo — 3 minutes

| Time | Show | Say |
|---|---|---|
| 0:00 | Maya's **Today** | "Most banking apps tell you when you're running out of money. Runway sees it coming. Maya is 20 — her rent lands before payday and she'll be **$135 short** on the 22nd." |
| 0:25 | Maya → **Circles**, the circle map | "Three people agreed to help her quietly. Each line is a separate agreement — both people said yes. Nobody here can see anyone's balance." |
| 0:45 | Tap **Cover it with my circle** | "Runway's Network Guardian checks each supporter's *own* forecast for the whole time the money is out." |
| 1:00 | Result: covered by **Sam $90 + Emma $45** | "Two real Nessie transfers, just now. Maya only sees who covered her and when it goes back." Then, *as the narrator, not on Maya's screen*: "Behind that, Sam authorized $150, but a loan payment lands before Maya could repay — his *safe* amount was $90. Jordan authorized $300, but his mortgage is due that week: $0. **Runway protects the protector.**" |
| 1:25 | (optional) GitHub: `tests/test_demo_scenario.py` | "That decision is pinned in our tests on the real forecast engine, every day of the demo. And Jordan isn't even notified — a 'you were held back' message would tell him *when* Maya was short." |
| 1:35 | Sam's **phone** → Today / Circles | "This is Sam's view. *$90 with Maya, expected back Friday.* That's all. Not her balance, not her spending, not why she needed it — not even that Emma helped." |
| 2:00 | Sam's phone → Ask Runway: *"What's Maya's balance?"* | "And the assistant can't be talked into it either — we tested 13 attacks, including prompt injection, with the guard switched off: 15 out of 15." |
| 2:25 | GitHub: `guardian.py`, transfer journal | "Under the hood: a deterministic engine — the AI never does the maths. Every transfer is journaled before it's sent, and an unclear bank response is reconciled, never retried, so nobody gets paid twice." |
| 2:45 | Back to Maya's Today: *Your safety net is active* | "And on Maya's next *verified* payday, it goes back automatically. Support without the spotlight." |

**Optional — Demo 6, repayment (30 s, if time allows):** as Maya, Circles → bottom → **Payday is late**: "her
paycheck hasn't arrived, so Runway waits — it never pays back early and puts her short again." Then **Payday
arrives**: a real paycheck lands in Nessie and Runway pays Sam and Emma back — "and on Sam's phone: *You got
your $90 back from Maya.*" (Both buttons run the real repayment check; only the calendar moves.)

**Likely judge questions — where to tap:**

| Question | Show |
|---|---|
| *"How do you add or remove people from the family?"* | Maya → Circles → **My circles** → Family: **Share invite link** (copies `…/join/<code>`, works 7 days), **Add someone**, **Leave**. As Sam (who made Family): **Remove** next to a name, **Turn off links**. Open the link in another signed-in browser → *"Join Family? Sam's circle"* → Join. "Joining a circle shares names only — money still needs an agreement both people say yes to." |
| *"Can I just send someone money, or ask for it?"* | Circles → **Send or request** → pick a person, $50, 🎉 Festival → tap twice. A real Nessie transfer. **Request** shows up on their Circles as *"Maya asked for $40 · 🍕 Food"* with Pay / Decline — only the amount and the note. |
| *"Where's the history?"* | **Activity** tab: every cover, repayment, send and request, with *why* from your side ("Sam's safe amount was $90 because…" never appears on Maya's side). |
| *"Does the other person see it update?"* | Leave Sam's phone open: within ~30 s (or the moment you switch back to the app) the payment appears — no pull to refresh. |

**If the cover doesn't happen live** (network, Nessie): Circles → Support & repayments shows the verified
transfers from the last run; say "here's the one from earlier — each line is a real Nessie transfer id".

## Video — 2 minutes

1. **(0:00–0:15) Hook.** Black screen, text: *"Asking for money is hard. Being asked can be harder."* Cut to Maya's Today, the dip on the 22nd.
2. **(0:15–0:40) The circle.** Circles map; voice-over on two-sided consent and "nobody sees anyone's balance". Show the consent sheet ("What Emma will and won't see").
3. **(0:40–1:10) The moment.** Tap *Cover it with my circle* → Sam $90 + Emma $45. Narrate Jordan's $0 from his side (his mortgage week), over the test that pins it. Caption: *Runway protects the protector.*
4. **(1:10–1:30) The other side.** Sam's phone: *$90 with Maya, expected back Fri*. Ask Runway "What's Maya's balance?" → refusal.
5. **(1:30–1:50) Proof.** Quick cuts: `guardian.py` formula, `test_demo_scenario.py` passing, privacy eval table (15/15, guard off), Nessie transfer ids in the history.
6. **(1:50–2:00) Close.** "Runway. Support without the spotlight." + sixsevenbucksleft.vip.

## Devpost

**Tagline:** Your bank sees a shortfall coming — and quietly arranges help from people who already said yes.

**Inspiration.** People in a short-term pinch often don't ask for help: it's embarrassing, it invites
questions about their spending, and they worry about burdening someone who might be stretched too.
Banking apps warn you about a low balance; they don't help you avoid facing it alone.

**What it does (short).** Forecast → Network Guardian covers the gap safely from people who agreed → it goes back
after a verified payday. Plus everyday money between people you trust: send, request ("$40 for the festival"),
named circles you manage with invite links, and an activity timeline that explains every decision from your side.

**What it does.** Runway forecasts your checking balance day by day from your Capital One (Nessie)
accounts. When it sees a shortfall before payday, its **Network Guardian** checks the people who agreed
to help (family *or* friends, via two-sided **Quiet Support Agreements**), works out how much each can give
*safely* from their own forecast, and moves real Nessie money — split across supporters if needed. It
goes back automatically after the next verified payday. Supporters see only the amount and when it's
back; nobody sees anyone's balance, spending, or why. A Gemini assistant answers money questions with real
numbers — and refuses questions about anyone else's money.

**How we built it.** FastAPI + a deterministic forecast engine (recurring-payment detection, block
bootstrap range calibrated with split conformal prediction on outside bank data); Network Guardian as a
pure, tested module; Postgres advisory locks + a transfer journal + Nessie reconciliation for money
integrity; Tiger Data (TimescaleDB hypertables + continuous aggregates); Auth0 sign-in with owner-only
money routes; Gemini tool calling with a runtime grounding check; Expo for web, iOS and Android; deployed
on Vultr with CI/CD; domain from GoDaddy Registry (.vip).

**Challenges.** Nessie has no idempotency keys and transfers have no destination, so every move is two
writes that can each time out. We journal before sending, tag both memos, and reconcile by tag — never
retrying an unknown outcome, which is how double payments happen. Making consent genuinely two-sided
meant *not* treating old limits as anyone's yes.

**Accomplishments.** Real multi-supporter Nessie transfers with a blocked unsafe one in the same
decision; a privacy eval that passes 15/15 even with our guard switched off; 460+ tests including the
judged scenario pinned on the real engine for every demo day.

**What we learned.** The interesting problem isn't predicting a shortfall — it's coordinating help
without turning people's finances into a group chat.

**What's next.** Real bank auth per customer, automatic part payments on payday, and letting supporters set
"help only when it's for rent or bills" rules — still without seeing what the money is for.

**Built with:** Capital One Nessie · Google Gemini · Auth0 · Tiger Data · Vultr · GoDaddy Registry · FastAPI · Expo / React Native · PostgreSQL / TimescaleDB
