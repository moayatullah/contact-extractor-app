import re
import requests
import csv
import random
from urllib.parse import urljoin, urlparse
from datetime import datetime
from threading import Thread
from html import unescape

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.progressbar import ProgressBar
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard


# ==================== CORE LOGIC ====================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
]

def is_valid_email(email):
    email = email.lower().strip()
    if len(email.split('@')[0]) < 4:
        return False
    garbage = ['www@', 'widget-', 'min.css', 'min.js', 'https%3a', 'googletagmanager', 'facebook.com', 
               'instagram.com', 'w3.org', 'google.com', '@min.', 'swiper', 'elementor', 'frontend', 
               'webpack', 'jquery', 'lazyload', 'example.com', 'john@example', 'test@', 'demo@']
    if any(g in email for g in garbage):
        return False
    domain = email.split('@')[-1]
    if '.' not in domain or len(domain.split('.')) < 2 or len(domain) < 5:
        return False
    return True


def extract_contacts(html, base_url):
    html = unescape(html)
    real_emails = set()

    candidates = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-z]{2,}", html)
    for e in candidates:
        if is_valid_email(e):
            real_emails.add(e)

    mailto = re.findall(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-z]{2,})', html, re.I)
    for e in mailto:
        if is_valid_email(e):
            real_emails.add(e)

    obs = re.findall(r'([a-zA-Z0-9._%+-]+)\s*(?:\[at\]|\(at\)| at |&#64;|@)\s*([a-zA-Z0-9.-]+\.[a-z]{2,})', html, re.I)
    for u, d in obs:
        email = f"{u.lower()}@{d.lower()}"
        if is_valid_email(email):
            real_emails.add(email)

    json_e = re.findall(r'"email"\s*:\s*"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-z]{2,})"', html, re.I)
    for e in json_e:
        if is_valid_email(e):
            real_emails.add(e)

    # Phones
    raw_phones = re.findall(r"\+?[\d\s\-\(\)]{10,}", html)
    phones = set()
    for p in raw_phones:
        clean = re.sub(r"[^\d+]", "", p)
        if not clean: continue
        if not clean.startswith("+") and clean.startswith("0"):
            pass
        elif not clean.startswith("+"):
            clean = "+" + clean
        digits = clean.replace("+", "")
        if not (10 <= len(digits) <= 15): continue
        if re.search(r"202[0-9]", clean) or re.search(r"(.)\1{6,}", clean): continue
        if clean.count("0") > len(clean)//2 + 3: continue
        phones.add(clean)

    return sorted(list(real_emails)), sorted(list(phones))


def find_contact_links(html, base_url):
    links = re.findall(r'href=["\'](.*?)["\']', html)
    keywords = ["contact", "about", "support", "info", "team", "connect", "privacy", "form", "quote"]
    results = []
    domain = urlparse(base_url).netloc.lower()
    for link in links:
        if any(k in link.lower() for k in keywords):
            if link.startswith(("mailto:", "tel:", "#", "javascript:")): continue
            full = urljoin(base_url, link)
            if urlparse(full).netloc.lower() in ("", domain):
                results.append(full)
    return list(set(results))


def fetch_page(url):
    try:
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        r = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        r.raise_for_status()
        return r.text
    except:
        return ""


def scan_website(base_url):
    visited = set()
    to_visit = [base_url]
    all_real = set()
    all_phones = set()
    visited_pages = []

    while to_visit and len(visited) < 15:
        url = to_visit.pop(0)
        if url in visited: continue
        html = fetch_page(url)
        visited.add(url)
        visited_pages.append(url)

        if html:
            real, phones = extract_contacts(html, base_url)
            all_real.update(real)
            all_phones.update(phones)

            for lnk in find_contact_links(html, base_url):
                if lnk not in visited:
                    to_visit.append(lnk)

    return list(all_real), list(all_phones), visited_pages


def save_to_csv(results, filename):
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Website", "Real Emails", "Phones"])
        writer.writerows(results)


# ==================== UI ====================
class MainLayout(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', padding=15, spacing=10, **kwargs)
        self.stop_scan = False
        self.results = []
        self.urls = []
        self.current_index = 0
        self.loading_dots = 0

        self.title = Label(text="[b]Contact Extractor[/b]", markup=True, size_hint_y=0.08, font_size=24)

        self.input_box = TextInput(hint_text="Enter websites (one per line)", size_hint_y=0.22)

        btn_layout = BoxLayout(size_hint_y=0.1, spacing=8)
        self.scan_btn = Button(text="Start Scan")
        self.scan_btn.bind(on_press=self.start_scan)
        self.copy_btn = Button(text="Copy All Emails")
        self.copy_btn.bind(on_press=self.copy_all_emails)
        self.export_btn = Button(text="Export CSV")
        self.export_btn.bind(on_press=self.export_results)
        btn_layout.add_widget(self.scan_btn)
        btn_layout.add_widget(self.copy_btn)
        btn_layout.add_widget(self.export_btn)

        status_layout = BoxLayout(size_hint_y=0.08, spacing=10)
        self.status = Label(text="Ready", size_hint_x=0.75)
        self.loading_label = Label(text="", size_hint_x=0.25, font_size=18)
        status_layout.add_widget(self.status)
        status_layout.add_widget(self.loading_label)

        self.progress = ProgressBar(max=100, value=0, size_hint_y=0.05)

        self.output = TextInput(readonly=True, size_hint=(1, 1))
        scroll = ScrollView(size_hint=(1, 0.47))
        scroll.add_widget(self.output)

        for w in [self.title, self.input_box, btn_layout, status_layout, self.progress, scroll]:
            self.add_widget(w)

    def start_scan(self, instance):
        self.output.text = ""
        self.progress.value = 0
        self.results = []
        self.urls = [u.strip() for u in self.input_box.text.splitlines() if u.strip()]
        self.current_index = 0
        self.stop_scan = False
        self.loading_dots = 0

        if not self.urls:
            self.status.text = "⚠️ Enter websites"
            return

        self.status.text = "Scanning"
        self.scan_btn.disabled = True
        Clock.schedule_interval(self.update_loading, 0.4)
        Clock.schedule_once(self.process_next, 0.1)

    def update_loading(self, dt):
        if self.stop_scan or self.current_index >= len(self.urls):
            self.loading_label.text = ""
            return
        self.loading_dots = (self.loading_dots + 1) % 4
        self.loading_label.text = "⟳" + "•" * self.loading_dots

    def process_next(self, dt=0):
        if self.stop_scan:
            self.status.text = "🛑 Stopped"
            self.scan_btn.disabled = False
            return

        if self.current_index >= len(self.urls):
            self.status.text = "✅ Completed"
            self.scan_btn.disabled = False
            self.progress.value = 100
            if self.results:
                fn = f"contacts_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.csv"
                save_to_csv(self.results, fn)
                self.output.text += f"\n\n✔ Saved to {fn}"
            return

        url = self.urls[self.current_index]
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        self.status.text = f"Scanning {self.current_index + 1}/{len(self.urls)}"

        def callback(real, phones, visited, error=None):
            if error:
                block = f"🌐 {url} [ERROR]\n{error}\n{'='*40}\n"
            else:
                block = f"""🌐 {url}
Visited {len(visited)} pages

📧 Real Emails ({len(real)}):
{chr(10).join('- ' + e for e in real) if real else 'None'}

📞 Phones ({len(phones)}):
{chr(10).join('- ' + p for p in phones) if phones else 'None'}

{'='*40}
"""
                self.results.append([url, ", ".join(real), ", ".join(phones)])
            self.output.text += block
            self.current_index += 1
            self.progress.value = (self.current_index / len(self.urls)) * 100 if self.urls else 0
            Clock.schedule_once(self.process_next, 0.2)

        Thread(target=lambda: self.scan_thread(url, callback), daemon=True).start()

    def scan_thread(self, url, callback):
        try:
            real, phones, visited = scan_website(url)
            Clock.schedule_once(lambda dt: callback(real, phones, visited), 0)
        except Exception as e:
            Clock.schedule_once(lambda dt: callback([], [], [], str(e)), 0)

    def copy_all_emails(self, instance):
        if not self.results:
            self.status.text = "No results"
            return
        all_emails = []
        for row in self.results:
            emails = [e.strip() for e in row[1].split(", ") if e.strip()]
            all_emails.extend(emails)
        if all_emails:
            text = "\n".join(all_emails)
            Clipboard.copy(text)
            self.status.text = f"✅ Copied {len(all_emails)} emails"
            self.output.text += f"\n\n📋 Copied {len(all_emails)} emails to clipboard!"
        else:
            self.status.text = "No emails found"

    def stop_scanning(self, instance):
        self.stop_scan = True
        self.status.text = "Stopping..."

    def clear_output(self, instance):
        self.output.text = ""
        self.status.text = "Cleared"

    def export_results(self, instance):
        if self.results:
            fn = f"contacts_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.csv"
            save_to_csv(self.results, fn)
            self.status.text = f"Exported to {fn}"
        else:
            self.status.text = "No results"


class MyApp(App):
    def build(self):
        return MainLayout()


if __name__ == "__main__":
    MyApp().run()