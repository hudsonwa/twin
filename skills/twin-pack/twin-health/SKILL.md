---
name: twin-health
description: "Check this twin's health with doctor, fleet and compare, then name the one next step."
version: 1.0.0
author: Grok Bot Twin
license: MIT
origin: plugin
metadata:
  hermes:
    tags: [twin, health]
    category: twin-pack
    origin: plugin
---

# Twin: Health

A read-only skill from the Grok Bot Twin plugin (origin: plugin). It is not one of your own skills and it is
never sent to Grok.

## When to Use

The user asks "is everything all right?", "are you in sync?" or "why did the last sync fail?".

## Steps

1. `hermes twin doctor`: the plugin, botport and Hermes checks. A failed line there comes first.
2. `hermes twin fleet`: whether the computers this twin lives on can reach each other (skip if it says none
   are linked).
3. `hermes twin compare TWIN`: each item, the same in Grok and Hermes or not. The plugin's own skills
   (this pack) are never counted.
4. Name the ONE next step: the first failing line's fix, word for word as the command printed it. If all pass,
   say so in one sentence.

## Rules

- Read only. Never run the fix yourself; give it to the user.
- Never guess: quote what the commands printed.

## Example (invented)

> Doctor passes. Compare: 11 of 12 items match; the skill "greet-visitors" differs. Next step:
> `hermes twin conflicts p-acme-support`.
