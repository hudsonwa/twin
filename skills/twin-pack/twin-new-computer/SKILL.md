---
name: twin-new-computer
description: "Walk the owner through putting this twin on another computer with a link code."
version: 1.0.0
author: Grok Bot Twin
license: MIT
origin: plugin
metadata:
  hermes:
    tags: [twin, computers]
    category: twin-pack
    origin: plugin
---

# Twin: New Computer

A read-only skill from the Grok Bot Twin plugin (origin: plugin). It explains the steps; the owner runs them.

## When to Use

The user says "make a twin on my other computer" or "put you on my laptop too".

## Steps

1. On the computer with the Grok app: `hermes twin setup --share --yes` prints a link code like
   `7KQ4-M2XD-P9RA` (invented). It links one computer and lasts 10 minutes.
2. On the other computer (Hermes and this plugin installed; no Grok app needed):
   `hermes twin setup --link 7KQ4-M2XD-P9RA --yes`.
3. Both computers must be on the same private network, and Hermes must be open on the sharing one.
4. `hermes twin fleet` on either computer then shows them linked.

Creating the twin remotely, from this chat, without a link code is experimental and may not be in this
version. Offer the link code as the way that works today.

## Rules

- Never run step 1 or step 2 yourself without the owner's yes, and never show a real link code in a shared chat.
- Do not list the owner's bots.
