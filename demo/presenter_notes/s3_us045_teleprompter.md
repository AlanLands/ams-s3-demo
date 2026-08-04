# S3 — US-2026-045 teleprompter

Word-for-word narration for the **EnrolDirect prospect-access** demo, scene by scene.

> **Verified end-to-end against a live run on 2026-08-04.** Every button label,
> number, badge and screen state below was read off the running console after a
> full four-script reset — not from the design docs. Where the old script and the
> real screen disagreed, the real screen won. Places where the app does something
> awkward are called out as **⚠ TRAP**.

**The voice:** plain English, short sentences, and *an everyday example before
every idea*. The audience is senior and mostly non-technical, and they have never
seen this screen. So every scene follows the same shape:

> **"Here's what you already do today. → Here's the same thing on screen. → That's
> the only difference."**

That is Seetha's *correlation* instruction — *"as I mentioned in the scenario
description, AI is expected to do this; look, this is what it is doing."*

**The one sentence the whole demo hangs off** — say it three or four times:

> **This is not AI replacing our process. It's the same process we already
> follow. AI is doing the typing.**

`s3_us045_run_sheet.md` is the timed beat list and pre-flight checklist. Read it
first; this is what you say once you're in the room.

> **Stage directions** in `[square brackets]`. Everything else is spoken.
> **The "In real life" boxes are the bit to memorise.**

---

## Before you share your screen

**Share one browser window — not your whole desktop.** Seetha stopped the
walkthrough twice over this. A terminal came into view and she said: *"What is
this code?"* … *"We should not get into the code now when you are
demonstrating."* … *"Is it possible to share a window?"*

Everything you need is in the browser. Terminals stay off-screen.

Tabs, in this order, before you share:

1. `docs/S3_SCENARIO_OVERVIEW.pdf`
2. EnrolDirect — `localhost:8083`
3. Console — `localhost:5173` *(not :8000)*

Logins: **Ravi Kumar / 1001** (engineer) · **Priya Nair / 1003** (tester).

### ⚠ The three traps that will bite you

1. **After logging in there is an extra screen.** You land on "AMS Service
   Console" with one card — you must click **"Open application →"** to reach the
   board. Don't be surprised by it; just click through while you talk.
2. **"Active work" starts on the wrong ticket.** As Ravi it defaults to
   **AMS-102**; as Priya it defaults to **AMS-101**. **Every stage will look
   locked until you click the AMS-1045 card on the board.** Do that first, every
   time you log in.
3. **Never reload the page or type a URL.** A reload throws Active work back to
   AMS-102 and every stage reads "Not available yet". Navigate only with the
   left-hand rail and the Next buttons. *(Recovery if it happens: go to Board,
   click the AMS-1045 card. One click, then carry on.)*

And the standing rule — *"don't explain everything, otherwise in 10 minutes you
cannot finish the scenario."* Key things only.

---

## SCENE 0 · The setup page — 3:00

**Screen:** `docs/S3_SCENARIO_OVERVIEW.pdf`, page 1. Console **not** open yet.

> The most important scene in the demo. Seetha asked for it four separate times.
> Do not cut it, do not shorten it, do not open the console until it's done.

**Three pages, in order.** Page 1 is the ground — what S3 is, why the insurer is
made up, and what EnrolDirect actually does. Page 2 is the change itself. Page 3
is what AI is expected to do about it. Don't skip page 1 to get to the change:
it's the page that stops the rest of the demo sounding like a code exercise.

### Page 1 — what you're looking at

> Before we start, three quick things — because everything after this makes more
> sense if you already know them. **What we're demonstrating. Why it's on an
> insurer you've never heard of. And what the application actually does.**

[Point at the first card.]

> So, the first one. This is **S3 — enhancement delivery.** And "enhancement" just
> means **a small change to an application that's already live**, already has
> people using it. Not a new build. Not a big programme. The kind of change your
> teams pick up most weeks — somebody asks for something small, and it still has
> to go through the whole machine.
>
> We're going to follow one of those, start to finish. It arrives as a written
> request on a board, and it ends as a released change with the paperwork behind
> it. **Five stages in between — and a person signs off at every one of them.**

[Second card.]

> Second. **MapleSure Insurance doesn't exist.** Neither do the employers, the
> contracts, or the people. All of it is invented — **there's no client code and no
> client data anywhere in this.**
>
> What *isn't* invented is the shape of it. Separate applications, owned by
> different teams, that depend on each other. And that matters, because a change
> like this usually goes wrong **between** two applications, not inside one.
>
> And these are running applications, not pictures. The code really does get
> changed.

[Third card.]

> Third — **EnrolDirect**. That's the one we're changing today.
>
> It's the website where somebody **joins their benefit plan themselves**, instead
> of ringing the service centre. Same idea as doing your banking on your phone
> rather than going into the branch.
>
> **So who's the user? The plan member.** An employee of one of our plan sponsors,
> sitting at home, joining their benefits. That's the one application in this demo
> whose user is outside the organisation — which is why the wording it puts on
> screen matters, and why a wrong "no" is a phone call to the service centre.
>
> And every one of them meets the same question on the way in: **is this person
> allowed to enrol online?**

[Now the row of boxes along the bottom. This is the bit to slow down on.]

> And here's the part I'd hold on to. **EnrolDirect doesn't decide that.** The
> employer — the plan sponsor — agrees who's allowed, at the point they sign the
> contract. **PolicyCore** stores that. **EnrolDirect** only enforces it.
>
> And on the right — three other systems read the answer. **DocumentHub** writes
> the confirmation pack we send out. **NightlyBatch** does the overnight numbers.
> **IntegrationBridge** passes the decision along.
>
> So: one small rule in the middle, with an employer's decision behind it, and
> three systems in front of it. **Keep that picture.** We come back to it twice —
> once when AI works out who else this affects, and once at the end.

### Page 2 — what the change is

> So that's the application. Now — **what the business has actually asked for.**
> Stay with me on this page, because once you know what's supposed to happen,
> you'll be able to follow the whole demo without me explaining it as I go.
>
> That one check I mentioned — *is this person allowed to enrol online.* Right now,
> **two** groups get through it. Existing members, and guests.
>
> **Currently only existing members and guests can enrol electronically — not
> prospects. And the change is to extend that capability to prospects. That's the
> change, all about.**
>
> Who's a prospect? Somebody already on the sponsor's list of people, who hasn't
> taken up a benefit yet. A real person on a real contract. They just haven't
> joined anything.
>
> And here's the thing — **nobody ever decided to turn those people away.** There
> was simply no rule for them. And when there's no rule, the system says no.
>
> So it's a small change. One rule. One group of people gets a yes instead of a
> no.

### Page 3 — what AI is expected to do

> Now this is the part to hold on to.
>
> Think about how a change like this normally gets done. A ticket lands on a
> developer's desk. They read it. They work out what it hits. They write the code.
> Someone reviews it. QA tests it. It gets released.
>
> **That's the process. We're not changing it.** All five steps still happen, and
> a person still signs off on every one of them.
>
> What changes is who does the typing.

[Walk the five boxes — one sentence each. Don't linger.]

> **One, analysis.** AI reads the request and the code together, tells us what's
> unclear, works out what's affected, and sizes it. It opens the ticket itself.
> **Two, picking the code.** It finds the right repository and narrows down which
> files it's even allowed to open.
> **Three, writing it.** AI writes the change. The developer reviews it, asks it
> questions, and accepts or sends it back.
> **Four, testing.** It plans the tests, writes them, runs them — and re-runs the
> old tests to prove nothing else broke. If something fails it goes back to the
> developer and comes round again.
> **Five, release.** It writes the release note, the go-live steps, and how to
> undo it.
>
> **A person signs off at every one of those five. The work does not move until
> they do.** AI does the labour. It doesn't make the decision.
>
> Right — let's watch it. And at the end we'll come back to the application and
> check that a prospect really can enrol.

**Don't walk pages 4–9.** They're there to answer a question without leaving the
demo, and to hand out afterwards.

---

## SCENE 1 · The application, saying no — 1:00

**Screen:** EnrolDirect `localhost:8083` → **Access check** (left-hand nav).

> **In real life:** *Before you fix anything, you go and look at it. You reproduce
> the problem. That's all this is.*

> **Say what screen this is before you touch it.** The audience has just been told
> the user is a plan member at home; if you then drive a dropdown of named people,
> somebody will quietly wonder who you are supposed to be. One sentence fixes it.

> This is the live application as it is this morning.
>
> And a word on what you're looking at, because this isn't the member's own screen.
> **This is the support team's view of the same check** — it lets us run one named
> person through it and see the answer, which is exactly what you'd do if a member
> rang up to ask why they couldn't get in. Same check, same rules. We can just
> watch it happen.

[Applicant dropdown → **Devon Achebe — PROSPECT · MS-2001**. Click **Check access**.]

> So I'll pick Devon Achebe. Devon is on the sponsor's list — we have him on the
> contract, Northwind Logistics — he just hasn't joined a plan. So Devon is a
> prospect.

[Red **DENIED** badge appears in the Decision panel.]

> **Denied.**
>
> And look at these two lines — **"Preference required"** and **"Authorised by."**
> They're both just a dash. There's nothing there. That's the whole problem in two
> characters: no rule exists for Devon, so nothing can let him in.
>
> And I want to be clear — that's not a bug. Nothing has crashed. The application
> is doing exactly what it was built to do.

[Read the reason line out — it says it better than you can:]

> *"Applicant category PROSPECT has no online enrolment preference and cannot be
> granted access."*
>
> **Remember those two dashes.** We come back to this exact screen in about ten
> minutes.

---

## SCENE 2 · The ticket lands — 1:00

**Screen:** console `localhost:5173`. Log in **Ravi Kumar / 1001** →
**Open application →** → Board → **click the AMS-1045 card**.

> **In real life:** *Work doesn't start with code. It starts with a ticket on a
> board. Same here.*

> This is our console — and you'll recognise it, because it's the same board the
> team already works from. To Do, In Progress, QA, Done.
>
> I'm logged in as Ravi Kumar, the developer who looks after this application.
> **AMS-1045**, sitting in To Do.
>
> And one thing before I open it. **Nobody typed this ticket.** The business wrote
> up what they wanted, that document went into the system, and the ticket opened
> itself, on the right person's board.

[Open the ticket. Point at the right-hand rail.]

> It even says so here — **Origin: business user story.** And down here in the
> history, the system's own log: *"story ticket created."* Nobody keyed that in.

> This is the business's own write-up — we didn't tidy it up for the demo. What
> they want, who it's for, and the acceptance criteria. That's the input to
> everything that follows.

---

## SCENE 3 · Analysis — 3:00 · *the biggest scene*

> **In real life:** *Think about what a good developer actually does when a ticket
> lands on their desk. They don't open the editor. First thing they do is
> analysis. They read the ticket, they go and read the code, and they come back
> with questions — because the ticket never says everything.*
>
> ***That is exactly what's about to happen.***

[Scroll to **AI ACTIONS** → click **Run AI impact analysis**.]

> That's step one on the page I showed you. Analysis.
>
> And the important bit is *what* it reads. Not just the request — the request
> **and the actual code, together.** That's the difference between summarising a
> ticket and understanding one.

### ⚠ TRAP — there are TWO questions, not one

It comes back with a clarifying question, you answer it, and **a second one
appears**. Both are pre-scripted below. Know both answers before you're on
screen — this is the beat most likely to produce dead air.

**Question 1** (about the guest preference):

> *"The existing guest preference is suitable for all prospect scenarios until
> further stakeholder feedback or testing suggests otherwise. Is that right?"*

Type: `Yes — treat prospects as guests. It is the narrower grant and matches the
recommendation.`

**Question 2** (about DocumentHub):

> *"DocumentHub will need to update confirmation pack wording to account for
> prospects classified as guests… Is that right?"*

Type: `Correct — DocumentHub owns that wording and will need a change.`

**Say this while you type:**

> Look what comes back first. **Questions.** Just like a developer would ask.
> It's telling us what's missing from the request — before anybody writes a line
> of code. Normally we find these gaps three weeks later in code review, or worse,
> in UAT.
>
> And notice it isn't guessing quietly. It tells me what it *would* have assumed,
> and asks me to confirm it. That's the first place a person has to say yes.
> Nothing moves until somebody answers.

[Analysis completes — about 20 seconds. Point at the status badge.]

> Now don't let this slip past. **The ticket has moved on its own.** It said To Do
> when I opened it. It now says **In Progress**. Nobody dragged a card.

### The cross-team result

[Point at the **✓ 1 other team affected** chip, then scroll to **Other teams
depended on**.]

> **In real life:** you know that moment — three weeks into a change somebody
> says *"hang on, does this affect the letters team?"* And it does. And now you're
> late.
>
> That conversation is happening here, on day one. **Those three boxes on the
> right-hand side of the first page — that's what it's just gone and checked.** It
> looked at every system that reads this decision, and this is the bit I'd point
> at: **only one of them actually has to write any code.**
>
> That's DocumentHub, because it writes the confirmation letter, and it's never
> had to write one for this kind of person before.
>
> The others are affected — their numbers move — but their **code** doesn't
> change. And that distinction matters, because if we'd raised a job on all of
> them, three other teams would be triaging work that doesn't exist.

[Point at the generated ticket body, then the **Create ticket in Jira** button.]

> And this isn't a one-line "you're affected." It's written the actual ticket that
> team receives — what changed, why it reaches them, and how to test it. One
> click and it's on their board.

> **⚠ Do NOT read the AI summary paragraph aloud.** The cached text contains a
> wrong figure — it says *"packsRequiringNewWording: 205 instances."* The real
> computed number is **2** packs under the recommended option (3 under the
> alternative). Talk over that paragraph, don't quote it. *(Known defect — see the
> note at the bottom of this file.)*

> **⚠ Don't feature the token panel.** On this scenario the scoped-vs-whole-app
> saving is only **1.1x**, which is an anticlimax. Skip it unless asked.

**Now reconcile — Seetha asked for this after every stage:**

> So against what I promised on that first page: it's read the request, read the
> code, asked us what it didn't know, sized the job, and told us the one other
> team we owe work to.
>
> Same as a developer would have done. It just did it in about twenty seconds.
> And a person accepted all of it.

---

## SCENE 4 · Picking the code — 1:00

[Left rail → **Target selection**.]

> **In real life:** *When a contractor comes to fix your kitchen, you don't hand
> them the keys to the whole house.*

> It's worked out which repository this belongs in **from the request itself** —
> and it says so: *resolved from the user story, no model call needed.* I didn't
> tell it where to go.

[Click **Check out the repo**.]

> And it cuts a branch. **`feature/AMS-1045-enroldirect-prospect-access`, off
> main.**
>
> That's what any developer would do first. You don't work on main.

[Click **Generate the change →**, then **Generate the change**.]

> Now it writes it. And two things to be clear about before it starts: this is a
> **separate branch**, and nothing has been applied to the real code. It's writing
> into a copy.

---

## SCENE 5 · The review — 3:00 · *Seetha: "this is very important"*

[The result: **four files**, each with a plain-English summary line.]

> Here's the change. Four files. And notice each one has a sentence saying what it
> does and why — that's for the human who has to review it.
>
> And read this line at the top: **"Nothing has been written to the repo yet."**
> This is a proposal. Not a change.

[Open **repos/enroldirect/applicants.py** → **Show diff**.]

> **Green is added. Red is removed.** This is how AI writes code. Now we have to
> check it.

> **⚠ Scroll past the first block.** The top of this diff is comments and
> documentation, which reads as waffle on a projector. **The readable code is in
> the second block** — `TREAT_AS_MEMBER`, `TREAT_AS_GUEST`, and
> `PROSPECT_POLICY = TREAT_AS_GUEST`. Land on that and stop scrolling.

> And that's the whole change, really. Two options written down, and one of them
> picked — the one the analysis recommended and the business agreed.

[Now the Ask box under the diff.]

> **In real life:** think about a normal code review. You open a pull request, you
> read somebody's code, and half the time you're guessing at *why* they did it
> that way. So you leave a comment — "why did you do this?" — and you wait until
> tomorrow.
>
> Watch this.

[Type: `Why did you put PROSPECT_POLICY at module level instead of passing it in
as a parameter?` → **Ask**. Takes about 10 seconds.]

> I can just ask it. Right now.

[Read the answer out. Then point at the last line of it:]

> And look at the bottom — **"Answered your question, no code was changed."**
> Asking it a question doesn't quietly rewrite anything. The developer stays in
> control.
>
> **The author is still in the room.** That's peer review, and it hasn't gone
> anywhere.

> There are three buttons here: **Ask, Apply this file, and Reject.** If the
> developer isn't happy, reject sends it back and it returns with a different
> proposal. I won't run that today, but that's the path.

> And I'm deliberately not going to walk you through what this code says. That's
> not the point. The point is AI has written the change and pulled every one of
> those changes into one place, ready to deploy — with a person's approval on it.

[**Apply to repo** at the bottom.]

---

## SCENE 6 · Apply it, and check — 1:30

[After apply: the **Source control** panel appears.]

> Applied. And this panel is worth ten seconds, because it's honest with you.
>
> Branch, apply, commit, push. And it says right here — **"modelled, not
> executed."** We are not pretending to have deployed anything. Commit is
> **gated on the tests passing**, and they haven't run yet.

[Switch to the EnrolDirect tab. Access check → **Devon Achebe** → **Check access**.]

> Now — the console restarted the application for us. Which matters, because
> otherwise the app is still running the old code and you'd be looking at a screen
> that hadn't changed.
>
> Same person. Same screen. Same check.

[Green **GRANTED**.]

> **He's in.**
>
> And remember those two dashes? **Preference required: Online Enrolment - Guest.
> Authorised by: Online Enrolment - Guest.** They're filled in.
>
> It's not just that he got through — it's that the system can say *which rule*
> let him through. That traces all the way back to the original request.
>
> **That's the red from ten minutes ago. Now it's green.**

> **If the restart banner says it couldn't restart:** say so and reload. *"The
> console is telling us it couldn't restart the app on this machine, so I'll
> refresh — and that's the new code."* Don't talk over the banner.

---

## SCENE 7 · Hand it to QA — 0:45

[Left rail → **Draft design doc (for QA)** → **Draft design doc**.]

> **In real life:** *You don't throw code over the wall. You write the hand-off
> note.*

> So before this leaves the developer — the hand-off document. Five sections, plus
> a map of what changed. What it does, which bits of the system it touches, and
> where QA should look.
>
> Built from what actually happened in this run — not written on a Friday
> afternoon from memory. And it downloads as a PDF **or as a Word document** —
> cover page, contents, document control, numbered sections. Same for the
> release document at the end.

[**Hand off to QA: Priya Nair** → **Assign tester & move to QA**. Then **Log out**.]

> And he hands it over — picks the tester, and the ticket moves to the QA column.
> From here **only the tester can run the next steps.**
>
> So I'll come back in as her.

---

## SCENE 8 · Testing — 3:00

[Log in **Priya Nair / 1003** → **Open application →** → Board → **click AMS-1045**.]

> This is Priya, the tester. And notice it's not just a different name — it's a
> different screen. She does **not** get the button that writes the code.
> Deliberately. Somebody who can rewrite the thing they're testing isn't really
> testing it.

**Four separate clicks here, in this order. The order is the point.**

[1 · **Draft test scenarios** → comes back with **10 scenarios**.]

> **In real life:** any tester will tell you the test plan comes first, and it
> gets agreed *before* anyone writes a test. Otherwise you're just writing tests
> that agree with the code that's already there.
>
> Ten scenarios. Positive, boundary, negative, regression. She can open any of
> them, see the setup and the test data, and change them or add her own.

[2 · **Approve test plan** → badge flips to **✓ Approved by Priya Nair**.]

> And she approves it. **Before a single test has been written.** That's the
> person saying yes at this stage — and it's got her name on it.

[3 · **Generate tests** → 4 · **Run tests**.]

> *Now* it writes them, and runs them. Real test run, live.

[**9 passed.**]

> Nine, all green.
>
> And here's where I'd normally expect somebody to be sceptical — of course the
> AI's tests pass, it wrote the code *and* the tests. So let's deal with that
> head-on, two ways.

[**Run regression suite** → **✓ 27 pre-existing tests still pass — no regression.**]

> First — this suite here was written by **people**, before any of this, and
> **AI is not allowed to write to it.**
>
> **In real life:** it's the checklist a surgeon fills in before an operation.
> Somebody else wrote it, and you don't get to edit the checklist to say you
> passed.
>
> Twenty-seven of them. All passing. Members and guests still work exactly as they
> did, alongside the new prospect route.

[**Inject a seeded bug & re-run** → **✓ The suite caught the injected bug — 4 tests
went red.**]

> And second — a passing test only means something if it would have failed when
> the code was wrong.
>
> So this deliberately **breaks the code**, re-runs the suite, and puts it back.
>
> And there it is — **the suite caught it. Four tests went red.** Then it reverted
> the bug; the code is untouched.
>
> That's the answer to "how do you know the tests are any good." We broke it on
> purpose and they noticed.

[**Build traceability matrix** → **! 5 of 8 criteria evidenced**.]

> And finally, every requirement in the request, against what actually proved it.
>
> And look — **five of eight.** It's telling us three of them are *not* covered by
> an automated test, and I'd rather be straight with you about why. Not everything
> can be. There are mainframe dependencies and other systems we can't reach from
> here.
>
> So those three are written down as **manual tests**. They're accounted for.
> They're not hidden. A tool that quietly reported eight out of eight would be
> lying to you.

---

## SCENE 9 · Release — 1:00

[Left rail → **Draft release notes** → **Draft release notes**.]

> Three release notes, not one — one for the customer, one for whoever runs the
> app, one for the help page. Same change, three audiences.
>
> Then the deployment and rollback plan. Three steps to deploy, two to roll back —
> and note what it says: **derived from the change's own service graph, not
> drafted by a model.** That order comes from which service calls which. It isn't
> a guess.
>
> And the release record — what shipped, the change map, the requirements matrix,
> every test run, the approvals, and the deployment plan. Downloads as a PDF.
>
> One thing I'd point at inside it: a section for **anything the pipeline could
> not evidence.** It states what this run did *not* prove. A release document that
> only lists the good news isn't a release document, it's marketing.

[**QA passed — mark ticket Done** → Board.]

> And the board goes to **Done**.
>
> **That concludes the enhancement.** From a written request on a board, to a
> released change — with a person signing off at all five stages.
>
> Same process we run today. AI did the typing.

---

## Lines to have ready

**CI/CD** — one sentence, then move on. **Do not open a pipeline.** Seetha: *"I
don't want to go to that SDLC pipeline again."*

> There's a YAML file already set up on the target branch, so pushing kicks the
> pipeline off automatically.

**"What if QA fails it?"** — the button is on screen in Scene 8 (*Failed QA —
hand it back*), so you can point at it without running it.

> It goes straight back. The ticket returns to In Progress, assigned to the
> developer who built it — worked out from the ticket's own history, not from
> somebody picking a name — with the tester's reason on the timeline.

**"Can we get the design document in Word?"** — she asked on the review call.
**This is now built.** There is a **⬇ Word** button next to Download PDF on the
design-doc stage, and another on the release stage. Show it rather than
describing it.

> Yes — there it is. It comes out with a cover page, a contents page, document
> control, and numbered sections, the same shape as the technical documents your
> teams already file. The contents page fills itself in when Word opens it.
>
> And where the run genuinely doesn't know something — who reviewed it, who
> countersigned it — it says **"TODO — SME input required"** rather than making
> a name up.

**⚠ If you open the Word file on the day:** Word may ask *"update the fields in
this document?"* — say **yes**; that is what builds the contents page. And the
sign-off tables are meant to be blank. Don't apologise for them; they're the
part a person fills in.

**"What's this release document called?"** — the retitle to "Change Request" was
asked for and is **held by the project owner**. Don't rename it on the day.

> We've followed one of our existing teams' models for these documents. Teams vary
> slightly, but this is one of the models actually in use.

**"Who actually uses EnrolDirect?"** — asked because the screen you demo is the
support view, not the member's. Answer both halves.

> The user is the plan member — an employee of one of our sponsors, joining their
> benefits themselves. The screen I showed you is the support team's view of the
> same check, which is what you'd open if that member rang in to ask why they were
> turned away. Behind both is one gate, and it is the gate we changed.

**"Where did the five systems come from?"** — the console only names DocumentHub.
The full map lives in the application's own analysis page.

> The application keeps its own map of everything downstream of this decision —
> five systems, each with a note on whether it has to change. I can show you after
> if it's useful.

**"How do we add another application?"**

> You drop the repository in, put its requests alongside, and add a short file
> saying what AI may read and what it may change. It registers itself. DocumentHub
> — the team we raised a job for earlier — was added exactly that way.

**"Does this work on mainframe / .NET / our stack?"** — don't volunteer it.

> The approach carries over — read the right bit of code, write a narrow change,
> check it, test it. But every stack needs its own plumbing: different tools to
> get the code, different way of running tests. For mainframe there are
> established tools this would sit on top of. I'd want a short session with your
> mainframe team before I put a date on it.

**If something breaks on screen** — say so.

> That's a live system, and that's a live failure. Give me a second.

---

## The five sentences you must not forget

1. **"Currently only existing members and guests can enrol electronically, not
   prospects — the change extends that capability to prospects."** (Scene 0)
2. **"This is the same process we already follow. AI is doing the typing."**
   (Scene 0, and again at the end)
3. **"The ticket moved from To Do to In Progress on its own."** (Scene 3)
4. **"Green is added, red is removed — this is how AI writes code, and now we have
   to check it."** (Scene 5)
5. **"Five of eight. Three aren't automated, and here's why."** (Scene 8)

## The four things you must not do

1. **Don't open the console before Scene 0 is finished.**
2. **Don't share anything but the browser window.** No terminal, no editor.
3. **Don't explain what the code does.** *"The point is not to explain what is
   written in the code, but to give a glimpse of how AI can create the change and
   compile all the code changes in one place for the deployment."*
4. **Don't reload the page, and don't click extra controls on an in-progress
   card.** Re-running the analysis on a ticket past To Do needs a reset. Her
   words: *"there could be chances we'll be clicking somewhere and the system
   would break."*

---

## Timing — measured on the live run

| Beat | Wall clock |
|---|---|
| Impact analysis, including both questions | ~20 s |
| Generate the change | ~10 s |
| Peer-review answer | ~10 s |
| Draft scenarios | ~8 s |
| Generate + run tests | ~10 s |
| Regression suite | ~5 s |
| Seeded-bug run | ~8 s |
| Design doc / release notes | ~8 s each |

The machine is not the bottleneck — **you are**. The 2026-08-03 walkthrough ran
over 15 minutes with no interruptions and the slot is ~15. Seetha: *"we'll try to
time it and practise over and over."*

The scenes above total ~17:30. Cut in this order:

1. Scene 5 to 2:00 — one diff, one question, apply.
2. Scene 3 to 2:30 — answer both questions, land the cross-team point, skip the
   effort and priority detail.
3. Scene 8 to 2:15 — approve the plan, run, regression, seeded bug, then name the
   5-of-8 without dwelling.

**Never cut Scene 0.**

**If you have to cut an analogy, cut the kitchen contractor (Scene 4) first.** The
three that carry the most weight are the developer-picks-up-a-ticket one (Scene
3), the code-review-comment one (Scene 5), and the surgeon's-checklist one
(Scene 8).

---

## Known defect found during the 2026-08-04 live run

**The AI impact-analysis summary quotes a figure that is wrong.** On screen it
says the change affects *"`packsRequiringNewWording`: 205 instances."* The value
computed by the application is **2** under the recommended (guest) option and
**3** under the alternative — `GET /api/analysis/prospect-impact` →
`documentImpact.perOption`.

The number is generated prose from a cached model response, so it will say 205
every time until that cache entry is re-recorded. **Do not read that paragraph
aloud**, and if a stakeholder reads it off the screen, correct it to two.

Everything else on that panel — the components, the effort, the priority, the
cross-team result and the generated ticket body — matched the application's own
figures.
