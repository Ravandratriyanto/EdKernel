"""Pre-flight for the lab server. start-lab.sh and start-lab.bat both run this
before starting, so the two launchers can't drift apart.

    python lab_setup.py

- shows which API keys are set (keycheck.py)
- switches settings.json into lab mode: login ON, guest sign-in ON, demo class OFF
- checks ADPASS, the password for the '4dmin' account that opens /chats
"""
from pathlib import Path

from dotenv import dotenv_values

import keycheck
import settings

# What the lab needs. Everything else in settings.json is left as it was.
LAB_FLAGS = {
    'auth_required': True,   # off = every visitor is the admin, and all chats land in one account
    'guest_login': True,     # students type a name, no password
    'stub_testing': False,   # hide the seeded demo class, so students only see Math
}


def main() -> None:
    keycheck.main()
    print()

    before = settings.load()
    after = settings.save({**before, **LAB_FLAGS})
    changed = [k for k in LAB_FLAGS if before.get(k) != after[k]]
    print('Lab settings (settings.json):')
    for key in LAB_FLAGS:
        note = '  <- changed' if key in changed else ''
        print(f'  {key:<14} {"on" if after[key] else "off"}{note}')
    print()

    env = dotenv_values(Path(__file__).with_name('.env'))
    # Only say set / not set — this window may be on the projector.
    if (env.get('ADPASS') or '').strip():
        print('Admin login:  username 4dmin, password = ADPASS in .env  (set)')
    else:
        print('WARNING: ADPASS is not set in .env, so you cannot log in as admin')
        print('         to watch the chats. Add a line like  ADPASS=some-long-password')
        print('         to .env, then restart this script.')


if __name__ == '__main__':
    main()
