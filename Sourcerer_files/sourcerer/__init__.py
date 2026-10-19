"""Sourcerer: keeps per-artist media collections in sync and drops new files into a library.

Layers, each importing only the ones above it:

    config     paths, the version, the user agent, setting defaults
    db         SQLite: artists, their sources, every file seen, settings
    accounts   logins: session cookies per site, from a login window or cookies.txt
    net        HTTP (requests): JSON and downloads, polite to every site
    imaging    picture fingerprints, sizes, thumbnails, avatars (Pillow)
    sources/   one module per site; each turns a URL into pages of media
    snapshots  the newest posts of a source as last seen, shared by sync, Browse and previews
    sync       runs the sources of an artist, downloads what is new, dedupes
    previews   the newest pictures of a card, found on the sites before any download
    follows    the accounts a login follows, made into listed cards (nothing read for them)
    security   the master password (the server answers 401 until it is given) and the reset
    updater    updates and repair: Sourcerer.zip, swapped in by a helper
    server     the Flask app the window talks to (API + static files)
    desktop    main(): starts the server, opens the window or the browser
"""
