import re

def is_url(path):
    return re.match(r'^https?://', path) is not None

def is_gdrive_link(url):
    return 'drive.google.com' in url 