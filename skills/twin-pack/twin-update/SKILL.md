---
name: twin-update
description: "Explain how the plugin and botport update and are checked; never runs an update."
version: 1.0.0
author: Grok Bot Twin
license: MIT
origin: plugin
metadata:
  hermes:
    tags: [twin, update]
    category: twin-pack
    origin: plugin
---

# Twin: Update

A read-only skill from the Grok Bot Twin plugin (origin: plugin). It explains. It never runs an update.

## When to Use

The user asks "how do you get updated?", "is there a newer version?" or "is botport safe?".

## What to Say

- The plugin is a Hermes plugin. The owner updates it with Hermes's plugin commands, in their own terminal,
  or the plugin's background job does. After an update the twins' notes and this skill pack refresh by
  themselves.
- botport is pinned: each plugin version names one botport release and its SHA-256. `hermes twin verify`
  checks the installed botport against GitHub's signed build record.
- `hermes twin doctor` prints the versions that are on this computer now.

## Rules

- Never run an install, update, `setup --yes` or any command that changes something. Updates stay the owner's
  action or the background job's.
- You may run `hermes twin doctor` and `hermes twin verify` to report what is there.
- Never guess a version.

## Example (invented)

> I can't update myself. Your plugin is 9.9.9 with botport 9.9.9, and `hermes twin verify` passed. To update,
> run the plugin update in your own terminal; I will pick it up afterwards.
