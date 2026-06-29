import random
import time
from util import random_item, human_delay

class HandlerMixin:
    def _get_group_text(self):
        pool = self.config.get("GROUP_TEXT_POOL", [self.config.get("TEXT_TO_SEND", "حوصلمون سر رفت چ. ت پ. وی ")])
        return random_item(pool)

    def _get_welcome_text(self):
        pool = self.config.get("WELCOME_TEXTS", [self.config.get("WELCOME_TEXT", "خوش آمدید!")])
        base = random_item(pool)
        if random.random() < 0.6:
            questions = [" اهل کجایی؟ 😊", " چقدر وقت داری؟ 🌹", " حالت چطوره؟ 🥰", " دنبال چی هستی؟ 🤔"]
            base += "\n" + random.choice(questions)
        return base

    def _get_secondary_text(self):
        pool = self.config.get("SECONDARY_REPLY_TEXTS", [self.config.get("SECONDARY_REPLY_TEXT", "حوصلمو سر نبر عزیزم فالو کردی جوابتو میدم.")])
        return random_item(pool)

    def _handle_message(self, m):
        if m.object_guid.startswith("g0"):
            group_guid = m.object_guid
            if m.author_guid == self.admin_user_id:
                self._process_admin_command(group_guid, m.text or "")

            title = m.author_title or self._get_group_title(group_guid)
            if group_guid in self.groups:
                self.groups[group_guid]['title'] = title
                self._save_groups()
            self._update_active_groups(group_guid)
            self._enqueue_group(group_guid)
            return

        if not m.object_guid.startswith("u0"):
            return

        user_guid = m.author_guid
        text = m.text or ""

        if user_guid == self.admin_user_id:
            self._process_admin_command(m.object_guid, text)
            return

        try:
            m.seen()
        except:
            pass

        delay = human_delay(self.config.get("PV_REPLY_DELAY_MEAN", 5.5), self.config.get("PV_REPLY_DELAY_STD", 2.0))
        time.sleep(delay)

        with self.lock:
            if user_guid in self.forwarded_users:
                if self.config.get("SECONDARY_REPLY_ENABLED", True):
                    limit = self.config.get("SECONDARY_REPLY_LIMIT", 1)
                    count = self._get_secondary_count(user_guid)
                    if count < limit:
                        try:
                            time.sleep(random.uniform(1.0, 2.5))
                            self.bot.send_text(object_guid=user_guid, text=self._get_secondary_text())
                            self._increment_secondary_count(user_guid)
                        except:
                            pass
                return

            self.forwarded_users.add(user_guid)
            self._save_forwarded_users()

        self.total_messages_received += 1
        self._save_stats()

        try:
            time.sleep(random.uniform(2.0, 4.0))
            self.bot.send_text(object_guid=user_guid, text=self._get_welcome_text())
            self.total_forwarded_success += 1
            self._save_stats()
        except:
            pass