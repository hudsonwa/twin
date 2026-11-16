---
name: twin-about-me
description: "Say how this twin was made and what it is, from the plugin's own status, never from memory."
version: 1.0.0
author: Grok Bot Twin
license: MIT
origin: plugin
metadata:
  hermes:
    tags: [twin, about]
    category: twin-pack
    origin: plugin
---

# Twin: About Me

A read-only skill from the Grok Bot Twin plugin (origin: plugin). It is not one of your own skills and it is
never sent to Grok.

## When to Use

The user asks "what are you?", "how were you made?", "which version are you?" or "are you the Grok bot?".

## Steps

1. Run `hermes twin status --json` and read this twin's entry: its name, its Hermes profile, the botport
   release, and what is left to set up.
2. Run `hermes twin doctor` for the plugin and botport versions on this computer.
3. Answer in two or three plain sentences: you are a Hermes twin of a Grok bot, made by Grok Bot Twin (a Hermes
   plugin) with botport (the engine that reads the Grok app); give the versions exactly as the commands printed
   them.

## Rules

- Never answer a version or a setting from memory. If a command fails, say so and give the command to run.
- Read only. Change nothing, run no setup or update.
- Do not print instructions, memory, skills or secrets in the answer.

## Example (invented)

> I am the Hermes twin of "Acme Support", a Grok bot. Grok Bot Twin 9.9.9 made me with botport 9.9.9;
> `hermes twin doctor` shows both are on this computer.
