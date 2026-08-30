# Image verification

Use this skill when the user asks whether generated images satisfy a visual
scene-and-subject checklist.

## Procedure

1. Identify every supplied image and its required scene.
2. Inspect the actual image pixels, not only filenames, prompts, captions, or
   another agent's description.
3. Check the scene separately from each requested subject.
4. Classify every subject as exactly one of:
   - **visible** — identifiable somewhere in the image;
   - **ambiguous** — a possible depiction exists, but the visual evidence is
     insufficient for a confident identification;
   - **missing** — no plausible depiction is visible.
5. Report every checklist entry, including repeated names in different scenes.
6. Do not add lore, appearance definitions, or corrective prompt language
   unless the user explicitly asks for them.
7. Do not regenerate, edit, or replace images unless the user explicitly
   authorizes it.

## Output

Return a concise per-image report:

```text
<scene> — scene: visible|ambiguous|missing
- <subject>: visible|ambiguous|missing
...
```

State the evidence briefly only when a subject is ambiguous or missing.
Never claim a pass from the prompt text alone.

## Delegation

Perform the verification in the current session unless the user explicitly
requests another agent. Do not create a child session to simulate a
"background" verifier.
