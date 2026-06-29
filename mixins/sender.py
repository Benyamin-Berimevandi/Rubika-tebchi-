import time
import queue
import threading
from datetime import datetime, timedelta

class SenderMixin:
    def _start_sender(self):
        if self.send_thread and self.send_thread.is_alive():
            return
        self.send_running = True
        self.send_thread = threading.Thread(target=self._sender_worker, daemon=True)
        self.send_thread.start()

    def _stop_sender(self):
        self.send_running = False
        if self.send_thread:
            self.send_thread.join(timeout=2)

    def _sender_worker(self):
        last_send_time = {}
        while self.send_running:
            try:
                group_guid = self.send_queue.get(timeout=1)
                if group_guid is None:
                    continue

                now = time.time()
                if group_guid in last_send_time and (now - last_send_time[group_guid]) < self.config["SEND_INTERVAL"]:
                    self.send_queue.put(group_guid)
                    time.sleep(0.5)
                    continue

                if not self._can_send_to_group(group_guid):
                    continue

                try:
                    text = self._get_group_text()
                    self.bot.send_text(object_guid=group_guid, text=text)
                    title = self._get_group_title(group_guid)
                    self._update_group_last_send(group_guid, title)
                    last_send_time[group_guid] = now
                    self._update_active_groups(group_guid)
                except Exception as e:
                    err = str(e).lower()
                    if any(w in err for w in ("not allowed", "permission", "send", "forbidden", "not found", "left")):
                        try:
                            self.bot.leave_chat(object_guid=group_guid)
                        except:
                            pass
                        self._remove_group_from_lists(group_guid)
                time.sleep(0.2)
            except queue.Empty:
                continue
            except:
                time.sleep(1)

    def _enqueue_group(self, group_guid):
        if self._can_send_to_group(group_guid):
            self.send_queue.put(group_guid)

    def _can_send_to_group(self, group_guid):
        if group_guid not in self.groups:
            return True
        last_send = self.groups[group_guid]['last_send']
        now = datetime.now()
        return (now - last_send) >= timedelta(minutes=self.config["COOLDOWN_MINUTES"])

    def _get_group_title(self, group_guid):
        try:
            info = self.bot.get_chat_info(object_guid=group_guid)
            return info.get('group', {}).get('group_title', 'ناشناس')
        except:
            return 'ناشناس'

    def _update_active_groups(self, group_guid):
        if group_guid not in self.active_groups:
            self.active_groups.append(group_guid)
            if len(self.active_groups) > 10:
                self.active_groups.pop(0)

    def _remove_group_from_lists(self, group_guid):
        if group_guid in self.active_groups:
            self.active_groups.remove(group_guid)
        if group_guid in self.groups:
            del self.groups[group_guid]
        self._save_groups()