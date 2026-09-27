"""Seed several fake students, each with a multi-turn tutoring conversation, so
the dev panel is populated with realistic multi-user data (Sessions list,
monitoring stats, and per-session drill-in).

    python -m stubtesting.seed_conversation

Idempotent: purges prior turns for these students first, so re-running leaves
exactly one clean conversation each (no pile-up). No LLM calls — the exchanges
are canned, so this needs no Groq key and is fully deterministic.
"""
import json
import random
import uuid

import sessionlog
import users

# (name, topic, [ (student, tutor, correct) ... ])
CONVERSATIONS = [
    ("billy", "expanding brackets", [
        ("hello", "Hi Billy! Ready to practise expanding brackets?", None),
        ("how do I expand 3(x-2)", "What do you get when you multiply 3 by each term inside?", None),
        ("3x - 6", "Exactly right. Now try 4(2x+5).", True),
        ("8x + 20", "Perfect — so add them: 3x-6 + 8x+20. What's the total?", True),
    ]),
    ("alice", "linear equations", [
        ("hi", "Hello Alice! Let's solve some equations. What are you working on?", None),
        ("2x + 7 = 19", "Good. What could you do to both sides to get 2x on its own?", None),
        ("subtract 7", "Yes! That gives 2x = 12. So what's x?", True),
        ("x = 6", "Spot on.", True),
    ]),
    ("carol", "factorising", [
        ("help me factorise x^2+5x+6", "Which two numbers multiply to 6 and add to 5?", None),
        ("2 and 3", "So how do you write it as two brackets?", True),
        ("(x+2)(x+3)", "That's it — nicely done.", True),
    ]),
    ("dave", "percentages", [
        ("what is 15% of 240", "What is 15% written as a decimal?", None),
        ("0.15", "Good — now multiply that by 240.", None),
        ("40", "Not quite — 0.15 x 240 isn't 40. Try it again carefully.", False),
        ("36", "There we go, 36 is correct.", True),
    ]),
    ("emma", "solving with negatives", [
        ("-3x = 12, is x = 4?", "Careful with the sign — you divided by -3. What sign should x have?", False),
        ("oh, x = -4", "Exactly — dividing a positive by a negative gives a negative.", True),
    ]),
    ("frank", "straight line graphs", [
        ("what does the m in y=mx+c mean", "It's the gradient. What does the gradient tell you about the line?", None),
        ("how steep it is", "Right. And c?", True),
        ("where it crosses y", "The y-intercept — exactly.", True),
    ]),
]


def _uid(name, pw):
    try:
        return users.create_user(name, pw, "student")
    except users.UserError:
        for u in users.list_users():
            if u["username"].lower() == name.lower():
                return u["id"]
        return None


def _purge(uids):
    keep = [r for r in sessionlog.read_records() if r.get("user_id") not in uids]
    with sessionlog.LOG_PATH.open("w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def seed():
    users.init()
    people = [(name, topic, turns, _uid(name, f"{name}pass123"))
              for name, topic, turns in CONVERSATIONS]
    _purge({uid for *_, uid in people})

    for name, topic, turns, uid in people:
        sid = str(uuid.uuid4())
        for i, (student, tutor, correct) in enumerate(turns):
            sessionlog.log_turn(
                "start" if i == 0 else "reply",
                session_id=sid, user_id=uid, mode="learn", topic=topic,
                input=student, output=tutor, correct=correct,
                latency_ms=random.randint(1200, 4800))
        print(f"{name:7} (id={uid}): {len(turns)} turns on {topic!r}")


if __name__ == "__main__":
    seed()
