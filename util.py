import random
import time
import threading

def random_item(value):
    if isinstance(value, list) and value:
        return random.choice(value)
    return value

def human_delay(mean, std):
    d = random.gauss(mean, std)
    return max(1.0, min(10.0, d))

class Animation:
    def __init__(self, status_callback):
        self.running = False
        self.thread = None
        self.status_callback = status_callback

    def start(self, base_text):
        self.running = True
        self.thread = threading.Thread(target=self._worker, args=(base_text,), daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)

    def _worker(self, base_text):
        frames = [
            "[▓▓▓▓▓▓▓▓▓▓] 100% 🚀",
            "[▓▓▓▓▓▓▓▓▓░]  90% 🔥",
            "[▓▓▓▓▓▓▓▓░░]  80% ⚡",
            "[▓▓▓▓▓▓▓░░░]  70% 💪",
            "[▓▓▓▓▓▓░░░░]  60% 🌟",
            "[▓▓▓▓▓░░░░░]  50% ⏳",
            "[▓▓▓▓░░░░░░]  40% 🌀",
            "[▓▓▓░░░░░░░]  30% 📥",
            "[▓▓░░░░░░░░]  20% ⏰",
            "[▓░░░░░░░░░]  10% 🌱"
        ]
        while self.running:
            self.status_callback(f"{base_text}\n{random.choice(frames)}")
            time.sleep(0.8)