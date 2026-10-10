"""Sourcerer: keeps per-artist media collections in sync and drops new files into a library.

Layers, each importing only the ones above it:

    config     paths, the version, the user agent, setting defaults
    db         SQLite: artists, their sources, every file seen, settings
    net        HTTP (requests): JSON and downloads, polite to every site
    imaging    picture fingerprints, sizes, thumbnails, avatars (Pillow)
    sources/   one module per site; each turns a URL into pages of media
    sync       runs the sources of an artist, downloads what is new, dedupes
    updater    updates and repair: Sourcerer.zip, swapped in by a helper
    server     the Flask app the window talks to (API + static files)
    desktop    main(): starts the server, opens the window or the browser
"""
