# Video Translator — Design System

Inspired by the cinematic restraint in Runway and the editorial clarity in ElevenLabs from [awesome-design-md](https://github.com/VoltAgent/awesome-design-md).

## Product feel
An understated desktop post-production tool. Make the source video the visual focus; keep controls quiet, legible and grouped by workflow. Use dark charcoal surfaces, cool muted text, thin borders and one restrained teal accent for progress/active states. Avoid decorative gradients, dense dashboards and oversized marketing UI.

## Tokens
- Canvas `#101112`; sidebar `#151718`; panel `#1b1e20`; raised `#222628`
- Main text `#f3f4f4`; secondary `#a6adaf`; muted `#727a7d`; border `#303638`
- Accent `#a7e5d3`; accent hover `#c0f0e2`; success `#7ec9a0`; warning `#efc27b`; error `#e28b8b`
- Font: Inter or system sans; body 14px, labels 12px uppercase with slight tracking, headings 22–28px medium
- Spacing: 4, 8, 12, 16, 24, 32; radius: 6px controls, 10px cards
- No drop shadows; use tonal surface changes and hairline borders for grouping.

## Layout and interaction
- Fixed narrow navigation rail; main workspace split into source/settings and a wide preview/status region.
- Primary action is a solid accent button; secondary actions are quiet outlined buttons.
- Show current source, output path, detected subtitle count, processing stage and progress plainly.
- Inputs have visible labels and useful defaults. Errors sit beside the affected input/action.
- Preview video with original audio; translation preview must show Vietnamese above Chinese.
- Keep advanced OCR, font, and model settings in a collapsible section.
- Provide responsive layout: stack panels below 900px; never hide the main action.

## Accessibility
- Maintain strong contrast, keyboard navigation, visible focus ring, explicit labels and non-color status indicators.
- Do not rely on placeholder text as labels. Progress reports stage and percentage in text.
