<!-- Generated from 'FIX AND RESTYLE.pdf' (text layer via pdftotext); the PDF is the original. -->

# FIX_AND_RESTYLE.md — repair the pipeline bug, then redesign the existing frontend. No architecture changes.

## Instructions to Claude Code:

1. This repo is a finished implementation of SPEC.md (the original one in this repo). Do not migrate it to any other spec, do not rewrite the backend, do not change the API contract, endpoints, SSE events, data models, sources, scoring or prompts. Only two jobs: (A) fix the bug in Part A; (B) replace the frontend's visual layer per Part B, keeping all existing data flow (api client, EventSource handling, state, routing, i18n plumbing).
2. Do not ask questions; record assumptions in DECISIONS.md under ## Fix & Restyle .
3. Small commits per step. Be economical: touch only files these two jobs require.

## Part A — Fix "found 123 → shown 0"

Real failure (user screenshot): query Al-Farabi Kazakh National University → header and description fine, but stats Нашли 123 → убрали 0 дублей и 0 нерелевантных → показываем 0 , all category tabs 0, warnings «Координаты университета не найдены в Wikidata» and «Источниĸ official_site недоступен».
This combination is diagnostic: 0 duplicates from 123 Commons candidates for a major university means dedup never ran on real images; 0 irrelevant means vision post-processing removed nothing; 0 shown means the photos died before selection or were all labeled unverified. Diagnose before fixing:
1. Add scripts/diagnose.py : run the pipeline in-process for a given name at DEBUG and print a stage table — candidates per source → after normalize → downloads ok/failed (with failure reasons) → dedup groups → vision batches sent/parsed/failed → removals per post-processing rule → label distribution (verified/likely/unverified) → shown/hidden. Print every caught exception with traceback.
2. Run it for Al-Farabi Kazakh National University and Massachusetts Institute of

Technology ; paste both tables into DECISIONS.md .
3. Fix what the table shows, checking these usual suspects (all of them, fix the real ones):
Silently swallowed exceptions: any except in the pipeline/download/dedup/vision/scoring path that logs nothing (or DEBUG-only) and returns [] . A stage failure must log WARNING with traceback and degrade per SPEC, never zero the list silently.
Downloads all failing: missing descriptive User-Agent on Wikimedia hosts (403), downloading the file page URL instead of thumburl , shared http client closed early, thumbnails not written to disk. If downloads fail, dedup/vision get nothing — which matches 0/0.
Vision failure removing photos: if the vision call errors (bad key, 429, parse failure), photos must REMAIN with heuristic categories, capped at likely , plus a vision-unavailable warning — not be dropped. If current code drops unclassified photos, that alone explains shown=0.
Selection filter bug: shown must be verified + likely, not verified only.
Wikidata P625 parser: Al-Farabi KazNU's Wikidata entity has coordinates, so «не найдены» is likely a parser bug — verify the code reads claims.P625[0].mainsnak.datavalue.value.latitude/longitude , skips snaktype != "value" , and uses "preferred ranks if any exist, else normal ranks" (filtering to preferred-only returns nothing when all ranks are normal). Save the real entity JSON as a fixture and unit-test the parser on it. Missing campus coords must disable only geo-dependent bits (distance, geo source), nothing else.
official_site fetch: confirm the fetcher sends a browser-like UA and follows redirects; verify with curl -IL whether kaznu.kz actually blocks us. If it truly does, the warning is correct — leave it.
Stats wiring: duplicates_removed / irrelevant_removed incremented in the stages themselves, not guessed at the end.
Gate A: scripts/diagnose.py "Al-Farabi Kazakh National University" → ≥ 15 shown photos, duplicates_removed > 0, coordinates parsed (or documented proof the entity lacks P625); same for MIT; no unlogged exceptions; existing tests still green.

## Part B — Frontend redesign: "the contact sheet"

The current UI is the generic AI template (blue links, rounded bordered cards, a stack of

yellow icon warning boxes, pill chips, breadcrumb steps, sidebar card, raw enum names like «campus» in Russian copy). Replace the visual layer completely. Keep: api.ts , EventSource/state logic, routing, types, i18n mechanism. Delete old presentational components rather than restyling them.

### B1. Art direction

The product is photographs and their provenance. The interface is a photographer's contact sheet: white lightbox surface, a strict grid of uniform frames, and one red editor's mark on verified shots. Photos are the only color on the page. No cards, no shadows, no gradients, no rounded corners, no icons/emoji. The one memorable moment: photos develop from grayscale into color as they stream in.

### B2. Tokens ( tokens.css , wire into Tailwind so utilities exist)

--paper #FFFFFF page; --ink #000000 text (true black); --ink-2 #6B6B6B secondary; -line #E4E4E4 1px rules/frames; --surface #F5F5F5 notices/skeletons; --mark #E3271A verified mark, progress line, search-field focus; --mark-soft #FBE9E7 verified row in the popover only. No other colors. No blue anywhere.

### B3. Type

Instrument Serif (display + description) and Instrument Sans (everything else), self-hosted via @fontsource packages, imported in main.tsx (verify exact css paths inside node_modules before importing); fallbacks Georgia/system-ui. font-featuresettings:"tnum" on all numbers. Scale: university name serif clamp(48px,9vw,128px)/0.92 ; home search field serif clamp(36px,6vw,80px) ; description serif 26/1.3 max 60ch; body sans 15/1.5; nav sans 15 weight 500; captions sans 13; license lines 12. Sentence case only. Forbidden: ALL-CAPS labels, letter-spaced eyebrows, monospace, Inter/Roboto.

### B4. Layout

8px grid; gutters 20/32/48px at 0/640/1024; full-bleed photo grid, text limited by ch; everything left-aligned, no centered hero; radius 0 everywhere; no shadows; links underlined (1px, offset 3px, hover 2px), no "→" suffixes; one button style: black rectangle, white text, 44px tall (hover --ink-2 ); secondary actions are underlined text links; exactly two 1px --line rules on the profile page (under the masthead, above the map); focus outline 2px --ink (search field --mark ).

### B5. Screens

Search ( / ): near-empty. Serif headline «Университет — таĸим, ĸаĸим его увидит

студент.» at 18vh; the huge serif input with only a 2px black bottom border; black button «Собрать профиль»; one body paragraph explaining the 30-second promise; example names as plain links (Nazarbayev University, ETH Zurich, University of Tokyo, Kostanay Regional University); footer caption naming the real sources. Placeholder types itself through 4 university names (55ms/char, hold 1.6s, delete 25ms/char, blinking 1px caret; stops on focus; plain setInterval hook). Candidate list = rows with 1px rules (label + description/city in --ink-2 ), keyboard navigable. Not-found and corrected-name states as plain sentences.
Profile ( /u/:qid ) top to bottom, single column:
1. 2px --mark progress line across the very top (15/45/60/90/100% by stage; fades 600ms after done).
2. Masthead: serif name; local name ( --ink-2 ); one line «Алматы, Казахстан. Кампус в 4,2 ĸм от центра города.» with underlined links «Официальный сайт», «Wikipedia» in the same line; cached line «Собрано N минут назад. Обновить» when cached. Then the 1px rule.
3. Status line (aria-live), body --ink-2 , one sentence that changes by stage — «Ищем фотографии в Wikimedia Commons и на официальном сайте» → «Проверяем, что снимĸи относятся ĸ университету» → «Расĸладываем по ĸатегориям и убираем дубли» → «Профиль готов за 18,4 с» — with live elapsed seconds (tabular digits, comma decimal).
4. Notices: ONE --surface block, padding 16px, plain sentences, no icons, no borders. Copy: low_data → «Проверенных фотографий этого университета в отĸрытых источниĸах мало. Поĸазываем тольĸо то, что удалось подтвердить.»; source_unavailable → «Источниĸ {name} сейчас недоступен, профиль собран без него.»; no_coordinates → «Координаты ĸампуса не уĸазаны в отĸрытых данных, ĸарта и расстояния недоступны.». missing_category is NOT a notice — it is the empty state inside its tab, worded with the Russian label: «В отĸрытых источниĸах не нашлось проверенных фото по ĸатегории «Общежития».» Never show internal enum names (campus/dormitory/...) to the user; map every enum to Russian in i18n.
5. Description as the serif lead paragraph; below it caption links «Источниĸи: Wikipedia (en), kaznu.kz» and the basis sentence («Описание построено тольĸо по Wikipedia»).
6. Stats as a plain sentence: «Нашли 123 снимĸа, убрали 21 дубль и 9 нерелевантных, поĸазываем 33.»
7. CategoryNav : one sticky row ( --paper bg, bottom 1px --line when stuck): Все N · Кампус N · Общежития N · Аудитории N · Библиотеĸи N · Лаборатории N · Спорт N ·

Студенчесĸая жизнь N · Город N, counts in --ink-2 ; active item has a 2px black underline that slides ( layoutId ); at the row's end the text toggle «Поĸазать непроверенные (N)». The old pill chips and the separate tab row are both replaced by this single row; the four case-required filters are the items «Общежития», «Спорт», «Лаборатории», «Студенчесĸая жизнь» (note in README they satisfy the case's filter requirement).
8. PhotoGrid : 4:3 frames, gap 12px, 2/3/4/5 columns at 0/640/1024/1440; lazy images; skeleton frames ( --surface with a subtle --line sheen) only while streaming. Each frame: image (cover, cursor zoom-in, click → lightbox), then two caption lines, leftaligned: line 1 = the mark + title-or-category; line 2 ( --ink-2 , underlined, links to source_page_url ) = «Wikimedia Commons, снято 4 мая 2019» / «…, дата неизвестна», appending «, 210 м от ĸампуса» when distance exists. The mark: verified = 10px filled --mark circle; likely = 10px black outlined circle; unverified = 10px dashed --ink-2 circle + 1px dashed frame outline (unverified hidden unless toggled). Click the mark → reasons popover.
9. ReasonsPopover : white, 1px --line border, ≤ 320px; first line «Подтверждено, уверенность 0,90» (verified row on --mark-soft ); then one Russian sentence per reason code (source, name-in-metadata, geo distance, vision check, etc. — take the sentences from i18n; write them if missing). Escape/outside closes; focus returns.
10. Lightbox : opaque --paper overlay; image left ≤ 68% (shared layoutId with the frame image), right column with title, category, mark+label, source, full date sentence, author, license, distance, then black button «Отĸрыть источниĸ» and underlined «Отĸрыть оригинал»; ×44px close, Escape, arrows navigate within the current tab; stacks vertically < 1024px.
11. Map section (only with coords): full-bleed, 420px, OSM tiles desaturated ( filter: grayscale(1) contrast(1.05) ), CircleMarker red for campus and black for city center, 1.5px black polyline, caption with the distance. Leaflet CSS imported; container height set explicitly.
12. Error state: «Не удалось загрузить профиль: {message}.» + black button «Попробовать снова».

### B6. Motion (use motion / framer-motion; ALL respect useReducedMotion → durations 0)

Only these exist: (1) the typing placeholder; (2) progress line width, 0.6s ease [0.22,1,0.36,1] ; (3) status sentence crossfade 120/200ms opacity-only; (4) develop: frames mount opacity 0, filter grayscale(1) brightness(1.18) → opacity 1,

grayscale(0) brightness(1) , 0.9s ease [0.16,1,0.3,1] , stagger 45ms within a batch, no translate/scale; (5) nav underline spring 420/40; (6) tab switch: incoming frames develop at 0.35s, outgoing instant; (7) lightbox shared-layout spring 300/34 + 180ms overlay fade; (8) popover 140ms scale 0.98→1; (9) unverified toggle opacity 200ms. Forbidden: hover scales, slide-up section entrances, parallax, spinners (skeletons only), animated gradients, count-ups.

### B7. Forbidden tells (treat as lint; check on screenshots)

Any blue accent; purple; gradients; glassmorphism; rounded corners; shadows; bordered cards; icons/emoji in UI; tinted near-black (#111) instead of #000; cream+terracotta; dark+acid-green; ALL-CAPS or letter-spaced labels; monospace data; «A · B · C» middot chains; «→» on links/buttons; centered hero; three-cards-in-a-row; Inter/Roboto; toasts; spinner loaders.

### B8. Writing

Russian default (English mirror via existing i18n): sentence case, active verbs on controls («Собрать профиль», «Отĸрыть источниĸ», «Обновить»), errors state what happened + next step without apologizing, Russian decimal comma and thin space before units («18,4 с», «4,2 ĸм»), dates in words («4 мая 2019»), no exclamation marks.

### B9. A11y / perf floor

Everything keyboard-reachable; visible focus; popover and lightbox trap and restore focus; alt text on images; --ink-2 contrast ≥ 4.5:1; content-visibility:auto on below-fold frames; 512px thumbs only.
Gate B: live run on a cold university: header ≤ 3s, first photos ≤ 10s, done ≤ 30s; the develop animation visible; single sticky nav row with the four required labels; every frame shows mark + underlined source + date sentence; popover and lightbox work by keyboard; grep built UI strings for campus|dormitory|classroom|library as user-visible literals → none; reduced-motion OS setting → static; screenshots (desktop 1440×900 + mobile 390×844) of home, streaming profile, finished profile, lightbox, popover saved to docs/screenshots/ and visually checked against B7 with violations fixed.

## Part C — Wrap-up (small)

Update README: new screenshots; note that the nav row items «Общежития/Спорт/ Лаборатории/Студенчесĸая жизнь» are the case's four filters; add any new fonts/libraries to «Готовые ĸомпоненты». Re-run scripts/eval.py ; commit EVAL.md . Final commit to

main .
