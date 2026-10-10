"""One module per site. Each offers:

    KIND, LABEL          the stored kind and its name on screen
    match(url) -> bool   whether a profile URL belongs to this site
    pages(url)           yields lists of Media, newest first, one API page each

A site that is not here yet is still accepted as a source and shown as "not
supported yet", so an artist card can list every place the artist posts.
"""
from dataclasses import dataclass

from . import bluesky, mastodon

SITES = [bluesky, mastodon]


@dataclass
class Media:
    remote_key: str      # unique per artist and file -- never downloaded twice
    url: str             # the original file, not a preview
    post_url: str
    posted: str          # ISO date the post was made
    name: str            # short id for the file name
    mime: str = ""       # content type when the site states it


def site_for(url):
    for site in SITES:
        if site.match(url):
            return site
    return None


def kind_of(url):
    site = site_for(url)
    return site.KIND if site else "unsupported"


def label(kind):
    return next((s.LABEL for s in SITES if s.KIND == kind), "Not supported yet")
