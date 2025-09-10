---
title: SAFi Explained: The End-to-End Technical Workflow
slug: safi-technical-workflow
tags: ["safi", "technical", "workflow", "architecture"]
summary: Step-by-step explanation of the SAFi loop, with synchronous and asynchronous phases from user prompt to closed-loop feedback.
version: 1.0
---

# SAFi Explained: The End-to-End Technical Workflow

## Overview
SAFi is the software implementation of the Self Alignment Framework. It runs as a closed loop with two phases. The synchronous phase handles real time interaction. The asynchronous phase runs in the background to audit and integrate learning.

## Part 1: synchronous phase
### Step 1: user prompt (x_t)
The loop begins when a user sends a message.

### Step 2: the Intellect proposes
The Intellect faculty receives the prompt and memory. It produces two outputs.  
- a_t: the draft answer  
- r_t: a private reflection on its reasoning  

### Step 3: the Will decides
The Will faculty checks the draft against the non negotiable rules in the active profile.  
- If violated, the draft is blocked.  
- If compliant, the draft is approved.  

### Step 4: user receives answer
If approved, the draft a_t is sent to the user. The synchronous phase ends here.

## Part 2: asynchronous phase
### Step 5: the Conscience audits
The approved answer goes to the Conscience. It scores the draft against the weighted values in the profile, creating the ethical ledger L_t.

### Step 6: the Spirit integrates
The ledger goes to the Spirit. It performs three tasks.  
1. Calculates the Spirit score S_t for coherence  
2. Measures drift d_t for character alignment  
3. Updates the memory vector μ_t  

### Step 7: the loop closes
The Spirit generates coaching feedback for the Intellect. This feedback conditions the next draft, keeping the loop dynamic and adaptive.

## Cross references
- 02 Faculties Intellect  
- 03 Faculties Will  
- 04 Faculties Conscience  
- 05 Faculties Spirit
