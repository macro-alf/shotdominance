#!/usr/bin/env python3
"""End-of-day report. Invoked by daily.py immediately before the PC sleeps.

Writes logs/report-YYYY-MM-DD.txt (full record) and logs/digest-YYYY-MM-DD.txt
(a compact pasteable summary), then sends a short Telegram note.

EVERY step is guarded. A failure in here must never prevent the PC sleeping -
that is why daily.py calls it through os.system() and ignores the exit code.
"""
import datetime as dt
import os
import subprocess
import sys

try:                       # force UTF-8 stdout (accented team names, Windows)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BAR = "=" * 74
SUB = "-" * 74


def run_review(args, timeout):
    try:
        r = subprocess.run([sys.executable, "review.py"] + args,
                           capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        out = r.stdout or "(review.py produced no output)"
        if r.stderr.strip():
            out += "\n--- review.py stderr ---\n" + r.stderr
        return out
    except Exception as e:
        return "  review.py could not run: %s" % e


def main():
    day = dt.datetime.now().strftime("%Y-%m-%d")
    os.makedirs("logs", exist_ok=True)
    rep = os.path.join("logs", "report-%s.txt" % day)
    p = ["END OF DAY REPORT   %s   (written %s)"
         % (day, dt.datetime.now().strftime("%H:%M:%S")),
         BAR, "", "1. DAY LIFECYCLE", SUB]

    dl = os.path.join("logs", "daily-%s.log" % day)
    try:
        p.append(open(dl, encoding="utf-8", errors="replace").read().rstrip())
    except Exception as e:
        p.append("  %s not available: %s" % (dl, e))

    ml = os.path.join("logs", "monitor-%s.log" % day)
    try:
        st = os.stat(ml)
        p.append("\n  monitor log: %s  %.0f KB  last written %s"
                 % (ml, st.st_size / 1024.0,
                    dt.datetime.fromtimestamp(st.st_mtime).strftime("%H:%M:%S")))
    except Exception as e:
        p.append("\n  monitor log not found: %s" % e)

    p += ["", "", "2. TODAY", SUB,
          run_review(["--dir", "logs", "--days", "1", "--top", "25"], 300),
          "", "", "3. CUMULATIVE - ALL DAYS", SUB,
          run_review(["--dir", "logs", "--top", "15"], 900)]

    text = "\n".join(p)
    try:
        with open(rep, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("[endday] wrote %s (%.0f KB)" % (rep, len(text) / 1024.0), flush=True)
    except Exception as e:
        print("[endday] could not write report: %s" % e, flush=True)
        return

    # A compact digest, sized to paste into a chat in one go.
    try:
        dig = os.path.join("logs", "digest-%s.txt" % day)
        keep = [("COVERAGE", 12), ("1. CLOSEST", 12), ("2. WHY METRICS", 14),
                ("3. DATA QUALITY", 14), ("4. GATE CENSUS", 14),
                ("5. CONVICTION", 6), ("6. BLOTTER", 12)]
        lines, out, cur, n = text.split("3. CUMULATIVE")[0].splitlines(), [], None, 0
        out.append("DIGEST %s  (paste this into the chat)" % day)
        out.append(SUB)
        try:
            dlines = open(dl, encoding="utf-8", errors="replace").read().splitlines()
            out += [l for l in dlines if any(k in l for k in
                    ("first kickoff", "last kickoff", "pacing:", "tracked fixtures",
                     "launching", "all tracked fixtures finished",
                     "hard stop reached", "monitor stopped", "END_ACTION",
                     "waiting", "exited early"))]
        except Exception:
            out.append("  (no lifecycle log)")
        for ln in lines:
            hit = next((k for k, _ in keep if ln.strip().startswith(k)), None)
            if hit:
                cur, n = hit, dict(keep)[hit]
                out += ["", ln.strip()]
                continue
            if cur and n > 0 and ln.strip() and not ln.startswith("="):
                out.append(ln.rstrip())
                n -= 1
        blob = "\n".join(out)
        open(dig, "w", encoding="utf-8").write(blob)
        print("[endday] wrote %s (%d lines)" % (dig, len(out)), flush=True)
    except Exception as e:
        print("[endday] digest failed: %s" % e, flush=True)

    try:
        from shotdominance import telegram
        keys = ("match-lines parsed", "checkpoint evals", "distinct matches",
                "signals fired", "bets logged")
        head = [l.strip() for l in text.splitlines()
                if l.strip().startswith(keys)][:len(keys)]
        telegram.Telegram().send(
            "End of day %s\n\n%s\n\nFull report: %s\nDigest to paste: %s"
            % (day, "\n".join("  " + h for h in head) or "  nothing parsed", rep,
               os.path.join("logs", "digest-%s.txt" % day)))
    except Exception as e:
        print("[endday] telegram summary failed: %s" % e, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[endday] fatal (ignored so the PC still sleeps): %s" % e, flush=True)
