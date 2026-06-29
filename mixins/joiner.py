import re
import time
import threading
from datetime import datetime
from util import Animation

class JoinerMixin:
    def get_linkdoni_ids(self):
        try:
            result = self.bot.search_global_objects(self.config["LINKDONI_QUERY"])
            return [obj['object_guid'] for obj in result.get('objects', [])]
        except:
            return []

    def extract_join_links_from_linkdoni(self, linkdoni_id):
        links = []
        try:
            last_id = self.bot.get_last_message_id(linkdoni_id)
            messages = self.bot.get_messages(linkdoni_id, last_id).get('messages', [])
            for msg in messages:
                found = re.findall(r'https://rubika\.ir/joing/\w{32}', msg.get('text', ''))
                links.extend(found)
        except:
            pass
        return links

    def fetch_all_join_links(self, linkdoni_ids):
        all_links = []
        for lid in linkdoni_ids:
            all_links.extend(self.extract_join_links_from_linkdoni(lid))
            time.sleep(0.5)
        return list(set(all_links))

    def join_group(self, join_link):
        try:
            group_info = self.bot.get_chat_preview(join_link).get('group', {})
            group_guid = group_info.get('group_guid')
            title = group_info.get('group_title', 'ناشناس')
            members = group_info.get('count_members', 0)

            if members <= self.config["MIN_MEMBERS"]:
                return {'status': 'skipped', 'title': title, 'members': members}

            self.bot.join_chat(join_link)
            if group_guid and group_guid.startswith("g0"):
                if group_guid not in self.groups:
                    self.groups[group_guid] = {'last_send': datetime.now(), 'title': title}
                    self._save_groups()
                self._enqueue_group(group_guid)
            return {'status': 'joined', 'title': title, 'members': members}
        except Exception as e:
            return {'status': 'failed', 'title': 'ناشناس', 'error': str(e)}

    def _join_loop(self, admin_chat):
        self.status_chat = admin_chat
        self.running = True
        self.stop_join = False

        try:
            res = self.bot.send_text(object_guid=admin_chat, text="🚀 آماده‌سازی...")
            self.status_msg_id = res['message_update']['message_id']
        except:
            self.running = False
            return

        saved_index, saved_links = self._load_progress()
        if saved_links and saved_index < len(saved_links):
            self.join_links = saved_links
            self.current_index = saved_index
            self._edit_status(f"🔄 ادامه از {saved_index+1}")
        else:
            linkdoni_ids = self.get_linkdoni_ids()
            if not linkdoni_ids:
                self._edit_status("❌ لینکدونی پیدا نشد")
                self.running = False
                return

            anim = Animation(self._edit_status)
            anim.start("📥 استخراج لینک‌ها...")
            self.join_links = self.fetch_all_join_links(linkdoni_ids)
            anim.stop()

            if not self.join_links:
                self._edit_status("❌ لینکی پیدا نشد")
                self.running = False
                return
            self.current_index = 0

        total_links = len(self.join_links)
        self.stats = {'joined': 0, 'skipped': 0, 'failed': 0, 'processed': self.current_index, 'total': total_links}
        self.update_status_message()

        self.bot.send_text(object_guid=admin_chat, text=f"✅ {total_links} لینک پیدا شد")

        batch_counter = 0
        for idx in range(self.current_index, total_links):
            if self.stop_join:
                break

            self.current_index = idx
            self.stats['processed'] = idx + 1
            self._save_progress(idx, self.join_links)

            result = self.join_group(self.join_links[idx])
            if result['status'] == 'joined':
                self.stats['joined'] += 1
                batch_counter += 1
                if batch_counter % self.config["BATCH_SIZE"] == 0 and self.config["AIRPLANE_MODE_PROMPT"]:
                    self.airplane_waiting = True
                    self.bot.send_text(object_guid=admin_chat, text="✈️ دسته کامل شد، (ادامه) بفرست")
                    self.continue_event.wait()
                    self.continue_event.clear()
                    self.airplane_waiting = False
            elif result['status'] == 'skipped':
                self.stats['skipped'] += 1
            else:
                self.stats['failed'] += 1

            if (idx + 1) % 5 == 0 or idx == total_links - 1:
                self.update_status_message()

            if idx < total_links - 1:
                time.sleep(self.config["DELAY_BETWEEN_JOINS"])

        self.running = False
        self.update_status_message(final=True)

        if self.stop_join:
            self.bot.send_text(object_guid=admin_chat, text="⏹ متوقف شد")
        else:
            self.bot.send_text(object_guid=admin_chat, text="🎉 همه لینک‌ها انجام شد")
            self._clear_progress()

        self.bot.send_text(object_guid=admin_chat, text=self._format_join_stats())
        self.join_thread = None

    def start_joining(self, admin_chat):
        if self.running:
            self.bot.send_text(object_guid=admin_chat, text="🌀 در حال اجراست")
            return
        if self.join_thread and self.join_thread.is_alive():
            self.bot.send_text(object_guid=admin_chat, text="⏳ صبر کنید...")
            return
        self.join_thread = threading.Thread(target=self._join_loop, args=(admin_chat,), daemon=True)
        self.join_thread.start()

    def stop_joining(self, admin_chat):
        if not self.running:
            self.bot.send_text(object_guid=admin_chat, text="❌ هیچ فرآیندی فعال نیست")
            return
        self.stop_join = True
        self.bot.send_text(object_guid=admin_chat, text="⏹ در حال توقف...")