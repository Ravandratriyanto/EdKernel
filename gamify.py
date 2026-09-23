MISSIONS = {'answer_5': ('Answer 5 questions', 'answer', 5), 'lesson_1': ('Start a lesson', 'lesson', 1), 'check_1': ('Check a working', 'check_working', 1)}
XP = {'answer_correct': 10, 'answer': 3, 'lesson': 15, 'check_working': 20, 'mission_complete': 25}
QUESTS = {'streak_7': ('Study 7 days in a row', 'streak', 7), 'xp_100': ('Earn 100 XP', 'xp', 100), 'master_3': ('Master 3 topics', 'mastery', 3)}

def level_for_xp(xp: int) -> int:
    return int((xp / 100) ** 0.5) + 1