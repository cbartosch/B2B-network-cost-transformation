# Review record

Five adversarial reviews of this codebase, in order. They are kept because the
findings explain why several controls are shaped the way they are, and because
a number of them are corrections to earlier fixes rather than to the original
build.

| File | Result |
|---|---|
| `audit-1.md` | 3 critical, 6 high, 8 medium, 7 low. The liveness proof and transport pinning were both defeatable |
| `audit-2.md` | 1 critical, 4 high, 6 medium, 5 low. Two findings were regressions from the first round's fixes, and `make test` destroyed the database |
| `audit-3.md` | 6 medium, 7 low. Contains a **withdrawn** finding — C3-01 was a false positive, retained with its correction rather than deleted |
| `audit-4.md` | 2 high, 4 medium, 4 low. The most serious were two correct fixes that disabled each other |
| `audit-5.md` | 2 high, 7 medium, 6 low. **Open.** A full sweep rather than a delta review: scope never previously examined, and one control that is a table, an endpoint and no implementation |

Rounds 1–4 are closed. **F-01 to F-05 of round 5 are closed** in build 4.8.0;
F-06 to F-15 remain open.

Two cautions worth carrying:

* Three of the first four rounds found defects introduced by the **previous
  round's fixes**, so "all findings closed" has never meant "correct".
* **180 of the 267 tests have never executed**, and neither has the
  application. The only two defects ever found by *running* something — a
  duplicate compose key and a bad `COPY` path — were invisible to five rounds
  of static review. `make test` is the next audit, and a better one.
