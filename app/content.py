"""Conservative rich-text cleanup. Keep Japanese formatting, never source scripts/styles."""
import hashlib
import html
import json
import re
from html.parser import HTMLParser
from uuid import NAMESPACE_URL, uuid5

ALLOWED = {'p', 'div', 'br', 'u', 'b', 'strong', 'i', 'em', 'ruby', 'rt', 'rp',
           'sub', 'sup', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'ul', 'ol', 'li'}
BLOCK = {'p', 'div', 'br', 'tr', 'li'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def stable_id(*parts):
    return str(uuid5(NAMESPACE_URL, 'manabi:' + digest(parts)))


class Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.text = []
        self.stack = []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'iframe', 'object'}:
            self.blocked += 1
        if self.blocked:
            return
        if tag in BLOCK:
            self.text.append('\n')
        if tag in ALLOWED:
            safe = ''
            if tag in {'td', 'th'}:
                safe = ''.join(f' {k}="{v}"' for k, v in attrs
                               if k in {'rowspan', 'colspan'} and v and v.isdigit() and 0 < int(v) <= 100)
            self.output.append(f'<{tag}{safe}>')
            if tag != 'br':
                self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != 'br':
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'iframe', 'object'} and self.blocked:
            self.blocked -= 1
            return
        if self.blocked:
            return
        if tag in self.stack:
            while self.stack:
                current = self.stack.pop()
                self.output.append(f'</{current}>')
                if current == tag:
                    break
        if tag in BLOCK:
            self.text.append('\n')

    def handle_data(self, data):
        if not self.blocked:
            self.output.append(html.escape(data))
            self.text.append(data)


def rich(value):
    parser = Cleaner()
    parser.feed(str(value or '').replace('\r\n', '\n').replace('\x00', ''))
    parser.close()
    parser.output.extend(f'</{tag}>' for tag in reversed(parser.stack))
    text = re.sub(r'\n[ \t]*\n+', '\n\n', ''.join(parser.text)).strip()
    return {'text': text, 'html': ''.join(parser.output).strip()}


def milliseconds(value):
    match = re.fullmatch(r'(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})', value or '')
    if not match:
        raise ValueError('Invalid subtitle timestamp')
    h, m, s, fraction = match.groups()
    if int(m) >= 60 or int(s) >= 60:
        raise ValueError('Invalid subtitle timestamp')
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(fraction.ljust(3, '0'))


class Subtitles(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.segments = []
        self.current = None
        self.invalid = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'p':
            self.finish()
            try:
                start = milliseconds(attrs.get('data-starttime'))
                end = milliseconds(attrs.get('data-endtime'))
                if end <= start:
                    raise ValueError('Invalid interval')
                self.current = {'start_ms': start, 'end_ms': end, 'text': ''}
            except ValueError:
                self.invalid += 1
        elif tag == 'br' and self.current:
            self.current['text'] += '\n'

    def handle_data(self, value):
        if self.current is not None:
            self.current['text'] += value

    def handle_endtag(self, tag):
        if tag == 'p':
            self.finish()

    def finish(self):
        if self.current:
            self.current['text'] = self.current['text'].strip()
            if self.current['text']:
                self.segments.append(self.current)
        self.current = None


def subtitles(value):
    parser = Subtitles()
    parser.feed(value or '')
    parser.finish()
    return sorted(parser.segments, key=lambda s: s['start_ms']), parser.invalid
