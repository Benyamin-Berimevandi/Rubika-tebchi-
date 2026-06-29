import threading
from bot import RubikaJoiner

ADMIN_USER_ID = "u0KFE6d0e440321c2e29651dd8271e17"
SESSIONS = ["teb", "temchi", "tebsi", "tabchos", "tabgoz", "tablas"]

threads = []
for sess in SESSIONS:
    joiner = RubikaJoiner(session_name=sess, admin_user_id=ADMIN_USER_ID)
    t = threading.Thread(target=joiner.run, daemon=True)
    t.start()
    threads.append(t)

for t in threads:
    t.join()