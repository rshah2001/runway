# Why Runway — pitch notes

## The one-liner
**Banking apps tell you what already happened. Runway tells you the exact day you'll run out — and
fixes it before it happens, with your family's pre-agreed help instead of an overdraft fee.**

## How we're different

| What people use today | What it does | The gap Runway closes |
|---|---|---|
| Budgeting apps | Show where money *went*, by category | Runway looks **forward**: a day-by-day balance for the next month, and the exact day you'd dip |
| Bank low-balance alerts | Fire when you're *already* low | Runway warns **days ahead**, while there's still time to fix it |
| Overdraft protection / overdraft-cover features | Cover you *after* you've overspent, often for a fee | Runway moves money **before** the dip, from your own savings or family, **no fees** |
| Cash-advance apps | Lend small amounts, often with subscription fees or "tips" | The **family safety net**: help from people who already agreed to it, auto-repaid on payday |
| Venmo / Zelle / Cash App | Move money **when someone asks** | Nobody has to ask: the agent knows the day you'll dip, checks helping is **safe for the helper too**, and repays them automatically |

**The short version:** others react after the problem. Runway predicts the day, acts within limits
*you and your family* set, and every number it says comes from a deterministic engine, never from
the AI.

## How it answers Capital One's challenge

> *"…leverages the Nessie API … accounts, merchants, bills, and peer-to-peer transactions … creatively
> integrate Nessie's endpoints to empower users and improve their financial lives."*

| The brief asks for | Runway |
|---|---|
| **Accounts** | Checking, savings and credit card per person; live balances computed from Nessie history |
| **Merchants** | 27 merchants with categories → spending breakdown and the subscription detective |
| **Bills** | Recurring bills are the forecast's backbone; paid bills form the history the model learns from |
| **Peer-to-peer** | Real money between real Nessie customers: splits, IOUs ("Alex owes you $45"), and the family safety net |
| **Creative use** | Nessie transfers no longer carry a recipient, so a move = transfer on the sender + deposit on the receiver; Nessie truncates cents, so we store minor units. Both found by probing the live API |
| **Empower users** | Overdrafts are prevented, not punished; the agent proposes and **people approve**; nobody has to make an embarrassing money ask |
| **Improve financial lives** | Three life stages, one family: Maya (20) stays out of overdraft, Jordan (40) sees $164/mo of subscription creep, Sam (60) helps safely and always gets repaid |

Nessie endpoints in use: customers, accounts (create / delete), merchants, purchases, deposits,
withdrawals, transfers (create / delete) and bills (recurring + completed).

## How it learns your money (and the Whoop comparison)

Whoop won't score you until it has watched you for a while. Runway works the same way: it learns
from your history before it predicts, and it should tell you how sure it is.

**What it learns today** (from the last 90 days, refit every time new data syncs, every 5 minutes):
1. **Your paycheck:** the amount and rhythm (biweekly, monthly), found from deposits.
2. **Your fixed bills and transfers:** rent, phone, card payment, and recurring P2P (a roommate's
   utilities split, a parent's allowance).
3. **Your subscriptions:** same merchant, steady amount, regular interval.
4. **Your everyday spending rate:** debit spending that isn't a bill (groceries, gas). Card purchases
   reach checking through the card-payment bill, so they're never counted twice.

**Measured, not claimed** (backtest: learn from months 1–3, predict month 4, 18 folds):
learning everyday spending cuts the daily balance error by **61%** versus bills alone ($160 vs $408),
and **19%** versus "repeat last month" ($197). The agent: **100% tool selection, 98% correct
answers, 100% of dollar figures traceable to the engine** on 42 questions.

**What we're adding** (Patil-Hemangi's round 2, `docs/TEAM_PROMPTS.md`):
- **A calibration period, like Whoop.** Until Runway has seen ~30 days of spending and two paychecks
  it says *"Learning your rhythm: day 12 of 30"*, and **the safety net won't move money
  automatically** on a forecast it doesn't trust yet.
- **A range, not a single number.** "Lowest point $180–$240 on Nov 5", and the safety net plans
  for the cautious end.
- **A learning curve.** Error vs days of history (14 / 30 / 60 / 90), showing it gets better the
  longer it knows you.
- **Its own report card.** Every day's forecast is saved and checked against what actually
  happened: *"My forecasts for you have been within ±$40 over the last 2 weeks."*
- **One-offs don't become habits.** A big unusual purchase is flagged and kept out of your normal
  spending rate.

## Guardrails to say out loud
- The AI never does math; a reply with any figure no tool produced is thrown away.
- The agent proposes; **people approve**. Real money only moves for the signed-in owner.
- The **lender** sets the safety-net limit; the money must come back **by the next payday**;
  helping must keep the **helper** safe too.
- Every bridge is visible to both people; nothing is funded or repaid twice.
