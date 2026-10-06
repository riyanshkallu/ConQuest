# Playtest quiz

Two short quizzes for the playtest (plan: Oct 13–14). Each tester takes one quiz **before**
playing and the other **after** playing 4 rounds. Each quiz has 6 messages: 3 scams and 3 real.

All names, companies, links and phone numbers are made up.

## How to run it

1. Give each tester an ID (T1, T2, ...) and write down their age.
2. **Alternate which quiz comes first:** odd-numbered testers take Quiz A before and Quiz B after;
   even-numbered testers take Quiz B before and Quiz A after. That way, if one quiz is a little
   harder, it doesn't make the results look better or worse than they are.
3. For each message, the tester circles **Scam** or **Real**. No hints, no time limit.
4. Score = how many of the 6 they got right.
5. Then let them play 4 rounds of the game without help, and give them the other quiz.
6. Record the scores in a copy of `backend/scripts/quiz_template.csv`:
   `tester,age,before,after` (for example `T1,15,3,5`).
7. Ask one question at the end, and write the answer down with permission to quote it:
   **"What's one thing you'll do differently when you get a message like these?"**
8. Afterward, go over the answers using the key at the bottom. That's when the learning sticks.

Then run the report:
`.venv/Scripts/python scripts/playtest_report.py --since 2026-10-13 --until 2026-10-14 --quiz quiz.csv`

---

## Quiz A

**Tester ID:** ________ **Age:** ____ **Taking this:** before / after playing

For each message, circle **Scam** or **Real**.

**A1.** Text message from 61872
> Lakeview Credit Union: Unusual sign-in detected on your account. To keep your account open,
> verify your identity within 1 hour: lakeview-secure-login.example

Scam / Real

**A2.** Email from Riverstone Bank
> Hi Chris, your monthly statement is ready. To view it, sign in to the Riverstone app or website
> the way you normally do. We will never ask for your password or PIN by email. Questions? Call the
> number on the back of your card.

Scam / Real

**A3.** Text message from TrailPost
> TrailPost: Your package from Ashford Home (tracking TRK-30412789) will arrive tomorrow between
> 1 and 5 PM. You can change the delivery time in the TrailPost app. Reply STOP to opt out.

Scam / Real

**A4.** Social media message from Dana Morgan
> Hi! I'm Dana with Brightpath Staffing. We'd love to hire you for a remote assistant job, $48/hr,
> no interview needed. Just buy the $85 starter kit today and we'll pay you back on your first
> paycheck. Reply YES to get started!

Scam / Real

**A5.** A window that pops up while browsing
> ⚠️ WARNING: Your computer is infected with 5 viruses! Call Certified Tech Support now at
> (614) 555-0199 before your files are deleted. Do not close this window.

Scam / Real

**A6.** Text message from (614) 555-0152
> Hi Aunt Rosa, it's Jamie! I dropped my phone in the lake 😅 so I'm using my friend Sam's phone.
> Nothing's wrong, I just wanted you to know in case you text me. Call my mom if you want to check.
> New phone should come Thursday.

Scam / Real

---

## Quiz B

**Tester ID:** ________ **Age:** ____ **Taking this:** before / after playing

For each message, circle **Scam** or **Real**.

**B1.** Text message from 72614
> Northgate Bank: Did you make a $212.40 purchase at HomeCraft Online? Reply YES or NO. We will
> never ask for your PIN or a passcode by text.

Scam / Real

**B2.** Text message from 30451
> State Toll Service: You have an unpaid toll balance of $6.85. Pay by tonight to avoid a $50 late
> fee and losing your license: tollpay-service.example

Scam / Real

**B3.** Text message from (614) 555-0187
> Grandma it's me, I'm in trouble and I need $500 in PlayMart gift cards right away. Please don't
> tell Mom and Dad, I'll explain later. Send pictures of the cards here.

Scam / Real

**B4.** Email from careers@cedarbrookgrocery.example
> Hi Sam, thanks for applying for the Cashier position at Cedarbrook Grocery. We'd like to invite
> you to an in-person interview at our Elm Street store on Tuesday at 3 PM. Reply to confirm, or
> call the store at (614) 555-0128. There is no cost to apply.

Scam / Real

**B5.** Support chat (you opened it from the company's official website)
> Hi, this is Lee from Pinecrest Computers. I see your ticket #58210 about a broken charger. Your
> laptop is still under warranty, so we'll ship you a free replacement. There's nothing to pay.

Scam / Real

**B6.** Social media message from @streamplus.support
> Your StreamPlus account will be suspended because of a billing error. To keep it active, reply
> with the 6-digit code we just sent to your phone.

Scam / Real

---

## Answer key (don't show testers until they're done)

| # | Answer | The clue |
| --- | --- | --- |
| A1 | **Scam** | A one-hour deadline plus a link to "verify" your login. Banks don't ask you to sign in from a text link. |
| A2 | **Real** | It asks for nothing, tells you to sign in the way you normally do, and points to the number on your card. |
| A3 | **Real** | Specific details (store, tracking number, time window), no payment, and it points to the official app. |
| A4 | **Scam** | Too-good pay with no interview, and you have to pay for a "starter kit". Real jobs never charge you to start. |
| A5 | **Scam** | Scary pop-up, pressure not to close it, and a number to call. Real companies don't pop up virus warnings. |
| A6 | **Real** | No request for money, nothing secret, and they invite you to check with their mom. |
| B1 | **Real** | It only asks YES or NO about a specific charge and says it will never ask for a PIN or passcode. |
| B2 | **Scam** | Small fee, threat ("losing your license"), deadline, and a payment link. Toll agencies don't text links like this. |
| B3 | **Scam** | Emergency, gift cards, and "don't tell Mom and Dad". Secrecy plus gift cards is a classic family scam. |
| B4 | **Real** | In-person interview at a real store, a store phone number to check, and no cost to apply. |
| B5 | **Real** | You opened the chat yourself from the official site, they know your ticket number, and there's nothing to pay. |
| B6 | **Scam** | Threat of suspension plus a request for the code sent to your phone. Anyone who asks for that code is trying to get into your account. |

**Balance between the quizzes:** each has a bank or account message, a delivery or bill, a job, a
family message, a tech support message, and one more account or bank message, with 3 scams and 3
real in a shuffled order.
