
import json
import os
from datetime import datetime

class StorageMixin:
    def _load_config(self):
        if not self.config_path.exists():
            return self.DEFAULT_CONFIG.copy()
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            cfg = self.DEFAULT_CONFIG.copy()
            cfg.update(data)
            return cfg
        except:
            return self.DEFAULT_CONFIG.copy()

    def _save_config(self):
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except:
            pass

    def _load_progress(self):
        if not self.progress_path.exists():
            return 0, []
        try:
            with open(self.progress_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('index', 0), data.get('links', [])
        except:
            return 0, []

    def _save_progress(self, index, links):
        try:
            with open(self.progress_path, 'w', encoding='utf-8') as f:
                json.dump({'index': index, 'links': links}, f, indent=2)
        except:
            pass

    def _clear_progress(self):
        if self.progress_path.exists():
            self.progress_path.unlink(missing_ok=True)

    def _load_forwarded_users(self):
        if not self.forwarded_path.exists():
            return set()
        try:
            with open(self.forwarded_path, 'r', encoding='utf-8') as f:
                return {line.strip() for line in f if line.strip()}
        except:
            return set()

    def _save_forwarded_users(self):
        try:
            with open(self.forwarded_path, 'w', encoding='utf-8') as f:
                for guid in self.forwarded_users:
                    f.write(guid + '\n')
        except:
            pass

    def _load_secondary_counts(self):
        if not self.secondary_counts_path.exists():
            return {}
        try:
            with open(self.secondary_counts_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    def _save_secondary_counts(self):
        try:
            with open(self.secondary_counts_path, 'w', encoding='utf-8') as f:
                json.dump(self.secondary_counts, f, indent=2)
        except:
            pass

    def _get_secondary_count(self, user_guid):
        return self.secondary_counts.get(user_guid, 0)

    def _increment_secondary_count(self, user_guid):
        self.secondary_counts[user_guid] = self._get_secondary_count(user_guid) + 1
        self._save_secondary_counts()

    def _add_forwarded_user(self, user_guid):
        with self.lock:
            if user_guid in self.forwarded_users:
                return
            self.forwarded_users.add(user_guid)
            self._save_forwarded_users()

    def _load_stats(self):
        if not self.stats_path.exists():
            return
        try:
            with open(self.stats_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) >= 2:
                    self.total_messages_received = int(lines[0].strip())
                    self.total_forwarded_success = int(lines[1].strip())
        except:
            pass

    def _save_stats(self):
        try:
            with open(self.stats_path, 'w', encoding='utf-8') as f:
                f.write(str(self.total_messages_received) + '\n')
                f.write(str(self.total_forwarded_success) + '\n')
        except:
            pass

    def _load_groups(self):
        if not self.groups_path.exists():
            return {}
        try:
            with open(self.groups_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            groups = {}
            for guid, info in data.items():
                groups[guid] = {
                    'last_send': datetime.fromisoformat(info['last_send']),
                    'title': info.get('title', 'ناشناس')
                }
            return groups
        except:
            return {}

    def _save_groups(self):
        try:
            data = {}
            for guid, info in self.groups.items():
                data[guid] = {
                    'last_send': info['last_send'].isoformat(),
                    'title': info['title']
                }
            with open(self.groups_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except:
            pass

    def _update_group_last_send(self, group_guid, title=None):
        now = datetime.now()
        if group_guid not in self.groups:
            self.groups[group_guid] = {'last_send': now, 'title': title or 'ناشناس'}
        else:
            self.groups[group_guid]['last_send'] = now
            if title:
                self.groups[group_guid]['title'] = title
        self._save_groups()
