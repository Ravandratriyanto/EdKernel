# Vision eval — worksheet to copy onto paper

Write each problem's lines exactly as shown, **one working line per physical
line**, one problem per photo. Shoot flat, decent light. Save as
`evals/vision_samples/vN.jpg`.

`error_index` is 0-based (the top line is 0). `null` = every step is correct.
This file is the answer key — when the photos are in, the `vision_cases.jsonl`
labels come straight from the last column.

---

## Correct working (error_index = null)

**v1** — Solve 2x + 7 = 19
```
2x + 7 = 19
2x = 12
x = 6
```
→ null

**v2** — Simplify 3(x + 2) + 2(x - 1)
```
3(x + 2) + 2(x - 1)
3x + 6 + 2x - 2
5x + 4
```
→ null

**v3** — Expand (x + 3)(x + 2)
```
(x + 3)(x + 2)
x^2 + 2x + 3x + 6
x^2 + 5x + 6
```
→ null

**v4** — Solve x^2 - 5x + 6 = 0
```
x^2 - 5x + 6 = 0
(x - 2)(x - 3) = 0
x = 2 or x = 3
```
→ null

**v5** — Solve 5x - 3 = 12
```
5x - 3 = 12
5x = 15
x = 3
```
→ null

**v6** — Solve 4x = 20   (write it a bit messy, cross something out — still correct)
```
4x = 20
x = 5
```
→ null

---

## Sign / arithmetic slips (error in one line)

**v7** — Solve 2x - 5 = 9   *(should be 2x = 14)*
```
2x - 5 = 9
2x = 4
x = 2
```
→ error_index = 1   (line 2 wrong: added -5 instead of +5)

**v8** — Solve -3x = 12   *(should be x = -4)*
```
-3x = 12
x = 4
```
→ error_index = 1   (line 2 wrong: sign dropped)

**v9** — Solve 3x + 4 = 2x + 9   *(should be 9 - 4)*
```
3x + 4 = 2x + 9
3x - 2x = 9 + 4
x = 13
```
→ error_index = 1   (line 2 wrong: sign when moving +4)

**v10** — Simplify 4(x - 3) + 2(x + 5)   *(should be 6x - 2)*
```
4(x - 3) + 2(x + 5)
4x - 12 + 2x + 10
6x + 2
```
→ error_index = 2   (line 3 wrong: -12 + 10 = -2, not +2)

---

## Wrong method from the first step (error_index = 1)

**v11** — Solve x^2 = 16   *(should be x = ±4)*
```
x^2 = 16
x = 8
```
→ error_index = 1   (halved instead of square-rooting)

**v12** — Simplify (x^3)(x^2)   *(should be x^5)*
```
(x^3)(x^2)
x^6
```
→ error_index = 1   (multiplied exponents instead of adding)

**v13** — Solve 2(x + 3) = 10   *(should be 2x + 6 = 10)*
```
2(x + 3) = 10
2x + 3 = 10
2x = 7
x = 3.5
```
→ error_index = 1   (didn't distribute the 2)

---

## Middle-step error (answer follows from the wrong line)

**v14** — Expand (x + 4)(x - 2)   *(should be x^2 + 2x - 8)*
```
(x + 4)(x - 2)
x^2 - 2x + 4x - 8
x^2 + 6x - 8
```
→ error_index = 2   (line 3 wrong: -2x + 4x = 2x, not 6x)

**v15** — Solve 3x + 6 = 21   *(should be 3x = 15)*
```
3x + 6 = 21
3x = 27
x = 9
```
→ error_index = 1   (added 6 instead of subtracting; x=9 follows from the wrong line)

**v16** — Solve 5(x - 2) = 15   *(should be 5x - 10 = 15)*
```
5(x - 2) = 15
5x - 2 = 15
5x = 17
x = 3.4
```
→ error_index = 1   (didn't distribute)

---

### Summary label table (for vision_cases.jsonl)

| id  | error_index | note |
|-----|-------------|------|
| v1  | null | correct |
| v2  | null | correct |
| v3  | null | correct |
| v4  | null | correct |
| v5  | null | correct |
| v6  | null | correct, messy |
| v7  | 1 | sign slip |
| v8  | 1 | sign dropped |
| v9  | 1 | sign moving term |
| v10 | 2 | combine sign |
| v11 | 1 | root vs halve |
| v12 | 1 | exponent rule |
| v13 | 1 | no distribute |
| v14 | 2 | middle combine |
| v15 | 1 | add vs subtract |
| v16 | 1 | no distribute |
