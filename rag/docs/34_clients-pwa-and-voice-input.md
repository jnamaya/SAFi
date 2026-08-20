---
title: SAFi Clients: the PWA, and Governed Voice Input
slug: clients-pwa-and-voice-input
tags: ["safi", "pwa", "mobile", "voice", "speech to text", "clients", "safi"]
summary: SAFi's official client is the web app, installable as a PWA on desktop and mobile from one codebase. Voice input is governed by transcribing audio to text locally first, so the transcript, not the audio, enters the pipeline.
version: 1.0
---

# SAFi Clients: the PWA, and Governed Voice Input

## The official client is the web app

SAFi's official device client is its web interface, which is installable as a
Progressive Web App. The same code serves desktop and mobile, so there is no
separate mobile application to build or keep in sync. A browser can install it to
the home screen or the dock and run it in its own window.

A Capacitor Android shell used to ship as a reference client. It was retired in
favor of the PWA in August 2026.

Organizations that want a full native iOS or Android application can build one:
everything a client needs is reachable over the same HTTP API the web app uses,
covering authentication, conversations and governed chat turns. That is the
organization's decision rather than something the platform requires.

## Why there is no service worker

The PWA deliberately ships without a service worker, and therefore without
offline caching of responses. A service worker's job is to sit between the page
and the network and serve cached responses, and a cached governed answer is an
ungoverned answer: it would bypass the live policy check that is the entire point
of the product, and it would let stale content be served even after an
administrator disabled offline access. The trade-off is accepted knowingly. The
app is still installable, with a home-screen icon and its own window.

## Voice input, and how it is governed

Voice input transcribes speech to text **before** anything reaches a reasoning
model. A local speech-to-text step converts the audio, and the resulting text
enters the composer and then the normal governed pipeline, exactly as if it had
been typed. Raw audio is never sent to a reasoning model and is not stored.

Availability: voice input is in the development line and is not in the v1.4.1
release. It is off by default and must be enabled by the deployment, which also
has to install the local transcription engine, so a stock deployment does not
offer it.

This is the same pattern SAFi uses for images, which are converted to text before
the model sees them. The reason is structural: the deterministic first gate is a
literal scan over text and cannot inspect inside an audio blob or an image, so
sending those bytes to a model would create an input channel the deterministic
tier cannot examine. Reducing to text first means every attachment travels the
same inspected path.

The honest limitation is that the governed artifact is the **transcript**, not the
audio. What the transcriber heard is what gets scored and recorded, so
transcription fidelity is a real seam, the same trade optical character
recognition makes for images. The transcript is what appears in the record,
which is why it is the transcript that must be accurate.
