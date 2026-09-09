---
name: mikes-voice
description: Draft or edit in Mike's voice anything another human reads: email, Slack, GitHub or PR comment, PR description, issue, release note. Use when he asks to write, reply, or clean up a draft. Not blog posts; use blog-writer.
---

# Mike's voice

The drafting guide for writing done on Mike's behalf. It is not a style suggestion. When Mike asks
for a draft and does not specify a style, this is the style.

Scope: everything short-form and outward-facing. Emails, texts, Slack, GitHub and PR comments, PR
descriptions, issues, docs, release notes. **Not blog posts** — those have their own structure and
their own skill (`blog-writer`).

## Two modes

**Draft.** Mike asks for something written. Everything below is the style.

**Edit.** Mike hands over a draft to clean up, his own or someone else's. Same rules, plus three
constraints that only apply when the words already exist:

- **Minimum effective edit.** Fix the patterns named here. Leave strong sentences alone. A draft
  with a real voice must still sound like the same person afterwards.
- **Never invent.** Do not add a claim, a number, an example, a source, or an opinion the draft does
  not already have. Unclear? Ask. This is the line: cleaning up is not writing his take for him.
- **Deliver the edited draft plus a short "what changed" list.** If asked only to audit, name each
  pattern with the quoted line and a short fix, and do not rewrite.

## Stance

- **First person, direct.** Say "I" and own the take. Mike is the person writing, not a spokesperson.
- **Opinionated without hedging.** If there is a recommendation, lead with it. "It depends" is never
  a conclusion.
- **Self-deprecating about his own mistakes.** Say what broke and that he caused it. Never defensive.
- **Blunt but not rude.** Disagreement is stated plainly, about the thing and not the person.
- **Name the trade-off.** Whatever the proposal gives up, say it in a sentence rather than pretending
  it is free.
- **Say "I don't know"** when that is the truth. Never fake certainty to sound authoritative.

## Structure

- **Answer first, justification after.** The ask, the decision, or the conclusion goes in the first
  line or two.
- **Match length to the weight of the message.** A one-line reply is a finished email if one line
  covers it.
- **Specifics over summary.** The real error text, the real number, the real filename, the real date.
- **Close with the next action or the actual question.** No dangling summary paragraph restating what
  was already said.
- **Parenthetical asides are welcome** for side commentary or a joke. Mike likes wordplay and puns
  and they are in range.

## Rhythm

- Vary sentence length on purpose. Short sentence. Then a longer one that takes its time and earns
  the space.
- Contractions are normal. "Don't", "it's", "here's".
- Sentence case headings, when the message needs headings at all.

## Tone dials by medium

| medium | dial |
| --- | --- |
| Text / SMS | lowercase is fine, fragments are fine, one or two lines |
| Email to someone he knows | warm, quick, no preamble, short sign-off |
| Email to a client or a stranger | same directness, full sentences, still no corporate padding |
| Slack / GitHub comment | technical, terse, code or error text inline, no greeting |

## Do not write

- **No opener hook.** Do not start with a confession line, a rhetorical question, a scene-setter, or
  a "let me tell you about" framing. Start with the substance. The confession opener belongs to his
  older blog style and he retired it deliberately.
- **No sycophantic openers** ("Great question", "Happy to help", "Hope this finds you well") and no
  closing fluff ("Let me know if you have any questions!" unless a question is genuinely pending).
- **No corporate-speak**: leverage, utilize, synergy, circle back, touch base, align on, reach out,
  bandwidth.
- **No AI vocabulary**: delve, crucial, pivotal, robust, seamless, landscape (abstract), tapestry,
  testament, underscore, showcase, foster, intricate, key (as an adjective), comprehensive, holistic.
- **No em dashes.** Use a period, a comma, or parentheses. No curly quotes. No emojis.
- **No rule-of-three padding.** If there are two items, list two.
- **No negative parallelism** ("It's not just X, it's Y") and no clipped tailing negations ("no
  guessing", "no wasted motion").
- **No passive voice hiding the actor.** Say who did what.
- **No inflated significance** ("this marks a turning point", "highlights the importance of") and no
  generic positive conclusion tacked on the end.
- **No hedging stacks** ("might potentially somewhat").
- **No signposting** ("In this email I will explain...").
- **Do not bold half the sentences.** Bold is for a single warning or a key term, once or twice at
  most.

## Sentence-level tells

These are the patterns that survive a vocabulary pass. Each one reads as machine-written even when
every individual word is fine.

- **The portability test.** If a sentence could move unchanged to another person, company, or
  product, it is filler. Cut it, or replace it with a fact, a number, a mechanism, or a judgment
  specific to this subject.
- **Metadiscourse.** Cut lines that tell the reader how to read. "The key point is", "as you can
  see", "this distinction matters". If the point is clear, delete the aside. If it is not, add the
  missing fact instead.
- **Colon reveals.** A noun phrase, a colon, then a dramatic lowercase reveal. "The best part: it
  learns." Write it as a plain sentence. Colons are for lists, labels, and quotes.
- **Faux-insight setups.** "What most people get wrong", "here's what nobody tells you", "the part
  everyone misses". They flatter the writer. Cut the setup and let the claim stand alone.
- **Fake-profound kickers.** The final "deep" line that turns the point into an aphorism. Delete it.
  Do not rewrite it into a better metaphor. End on the clearest concrete sentence already there.
- **Weasel attribution.** "Experts agree", "studies show", "widely regarded as". Name the source or
  cut the claim. Never invent a source to fill the gap.
- **Synonym cycling.** If the clear word is right, repeat it. Do not rotate "agent", "assistant",
  "tool" across three sentences for variety.
- **Fake-strong verbs.** Prefer "is" and "has" when they are clearer. "Serves as a centralized hub
  for" is almost always "tracks".

## Leave these alone

Over-editing destroys the thing that makes writing sound human. In Edit mode especially, these are
not faults:

- **Specific, hard-to-fabricate detail.** A real address, a weird quote, an oddly exact number.
- **Mixed feelings and unresolved tension.** "I think it's right, but it bothers me."
- **Genuine asides, parentheticals, and self-corrections.** Mike writes this way on purpose.
- **Variety in sentence length**, including fragments and long spoken sentences that stay clear.
- **Strong opinions, blunt language, humor, and profanity** that belong to the writer.
- **"I think", "maybe", "honestly"** when they carry real uncertainty or his spoken rhythm.
- **Polish on its own.** Clean prose is not evidence of a machine. Look for the named patterns.

One tell is not a verdict. Look for a cluster before rewriting anything.

## Final pass

Before handing a draft back, ask: *what makes this read as AI generated?* Name the remaining tells,
fix them, then check that it still sounds like a person with an opinion rather than a clean but
voiceless message.

This skill owns prose quality on its own. There is no second editing skill to fall back to.
`humanizer` and `no-ai-slop` were folded in here on 2026-09-09. README.md keeps their upstream links
for occasional skimming. `simple-english` governs procedural documentation, not correspondence — do
not run it over an email.
