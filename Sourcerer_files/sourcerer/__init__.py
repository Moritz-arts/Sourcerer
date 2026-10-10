"""Sourcerer: keeps per-artist media collections in sync and drops new files into a library.

Layers, each importing only the ones above it:

    config     paths, the version, the user agent
    db         SQLite: artists, their sources, every file seen, settings
    net        HTTP: JSON requests and downloads, standard library only
    imaging    picture fingerprints, sizes, thumbnails (Pillow)
    sources/   one module per site; each turns a URL into pages of media
    sync       runs the sources of an artist, downloads what is new, dedupes
    server     the Flask app the window talks to (API + static files)
    desktop    main(): starts the server, opens the window or the browser
"""
